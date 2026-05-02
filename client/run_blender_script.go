/*##### BEGIN GPL LICENSE BLOCK #####

  This program is free software; you can redistribute it and/or
  modify it under the terms of the GNU General Public License
  as published by the Free Software Foundation; either version 2
  of the License, or (at your option) any later version.

##### END GPL LICENSE BLOCK #####*/

// POST /run_blender_script — generic "run a Python recipe under
// headless Blender" endpoint.
//
// Caller picks a recipe via:
//   - script_id   : looks up <exe_dir>/tools/<id>.py (set
//                   $BLENDERKIT_TOOLS_DIR to override). Use this for
//                   stable recipes shipped with the binary.
//   - script_path : absolute path to a caller-supplied script. Escape
//                   hatch for embedder-specific work.
//
// `params` is forwarded to the script as a temp JSON file (passed as
// the last arg after `--`); the recipe parses it. The client never
// inspects the params, so embedders evolve schemas freely.
//
// `blender_exe_path` is required: callers know where their Blender is
// (Blender add-on uses `bpy.app.binary_path`; external embedders
// resolve it themselves). Keeps the client out of platform-specific
// install-path discovery.

package main

import (
	"bufio"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"sync"

	"github.com/google/uuid"
)

// RunBlenderScriptData is the JSON body of POST /run_blender_script.
// Caller MUST set exactly one of ScriptID or ScriptPath, plus
// BlenderExePath.
type RunBlenderScriptData struct {
	ScriptID   string `json:"script_id,omitempty"`
	ScriptPath string `json:"script_path,omitempty"`

	BlenderExePath string `json:"blender_exe_path"`

	BlendPath  string                 `json:"blend_path,omitempty"`
	OutputPath string                 `json:"output_path,omitempty"`
	Params     map[string]interface{} `json:"params,omitempty"`

	StatusMessage   string `json:"status_message,omitempty"`
	AppID           int    `json:"app_id"`
	AddonVersion    string `json:"addon_version"`
	PlatformVersion string `json:"platform_version"`
	Software        string `json:"software"`
}

func runBlenderScriptHandler(w http.ResponseWriter, r *http.Request) {
	body, err := io.ReadAll(r.Body)
	if err != nil {
		http.Error(w, "Error reading request body: "+err.Error(), http.StatusInternalServerError)
		return
	}
	defer r.Body.Close()

	var data RunBlenderScriptData
	if err := json.Unmarshal(body, &data); err != nil {
		http.Error(w, "Error parsing JSON: "+err.Error(), http.StatusBadRequest)
		return
	}
	if data.ScriptID == "" && data.ScriptPath == "" {
		http.Error(w, "either script_id or script_path is required", http.StatusBadRequest)
		return
	}
	if data.ScriptID != "" && data.ScriptPath != "" {
		http.Error(w, "set either script_id or script_path, not both", http.StatusBadRequest)
		return
	}
	if data.BlenderExePath == "" {
		http.Error(w, "blender_exe_path is required", http.StatusBadRequest)
		return
	}

	taskID := uuid.New().String()
	go doRunBlenderScript(data, taskID)

	respJSON, _ := json.Marshal(map[string]string{"task_id": taskID})
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	w.Write(respJSON)
}

// resolveBundledScript maps a script_id to an absolute file path.
// Lookup order:
//  1. $BLENDERKIT_TOOLS_DIR/<id>.py   - explicit override (dev)
//  2. <exe_dir>/tools/<id>.py         - production layout
//  3. <cwd>/tools/<id>.py             - `go run` dev fallback
func resolveBundledScript(id string) (string, error) {
	if env := os.Getenv("BLENDERKIT_TOOLS_DIR"); env != "" {
		p := filepath.Join(env, id+".py")
		if _, err := os.Stat(p); err == nil {
			return p, nil
		}
	}
	if exe, err := os.Executable(); err == nil {
		p := filepath.Join(filepath.Dir(exe), "tools", id+".py")
		if _, err := os.Stat(p); err == nil {
			return p, nil
		}
	}
	if cwd, err := os.Getwd(); err == nil {
		p := filepath.Join(cwd, "tools", id+".py")
		if _, err := os.Stat(p); err == nil {
			return p, nil
		}
	}
	return "", fmt.Errorf("script_id %q not found (looked under $BLENDERKIT_TOOLS_DIR, <exe>/tools/, <cwd>/tools/)", id)
}

func doRunBlenderScript(data RunBlenderScriptData, taskID string) {
	TasksMux.Lock()
	if Tasks[data.AppID] == nil {
		BKLog.Printf("%s run_blender_script: AppID %d not subscribed yet — registering it.", EmoWarning, data.AppID)
		SubscribeNewApp(MinimalTaskData{AppID: data.AppID})
	}
	task := NewTask(data, data.AppID, taskID, "run_blender_script")
	task.Message = "Queued"
	Tasks[data.AppID][taskID] = task
	TasksMux.Unlock()

	scriptPath := data.ScriptPath
	if scriptPath == "" {
		var err error
		scriptPath, err = resolveBundledScript(data.ScriptID)
		if err != nil {
			TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID, Error: err}
			return
		}
	}

	// Cache: skip the run if the requested output already exists.
	if data.OutputPath != "" {
		if info, err := os.Stat(data.OutputPath); err == nil && info.Size() > 0 {
			TaskFinishCh <- &TaskFinish{
				AppID: data.AppID, TaskID: taskID,
				Message: "Cached output already present",
				Result:  map[string]interface{}{"file_path": data.OutputPath},
			}
			return
		}
	}

	if data.BlendPath != "" {
		if _, err := os.Stat(data.BlendPath); err != nil {
			TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID,
				Error: fmt.Errorf("blend file missing: %s", data.BlendPath)}
			return
		}
	}
	if _, err := os.Stat(scriptPath); err != nil {
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID,
			Error: fmt.Errorf("script file missing: %s", scriptPath)}
		return
	}
	if _, err := os.Stat(data.BlenderExePath); err != nil {
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID,
			Error: fmt.Errorf("blender_exe_path not found: %s", data.BlenderExePath)}
		return
	}

	statusMsg := data.StatusMessage
	if statusMsg == "" {
		statusMsg = "Running script…"
	}

	// Materialize Params to a temp JSON file. The recipe reads it from
	// sys.argv[-1] (every script in tools/ follows this convention).
	var paramsPath string
	if data.Params != nil {
		f, err := os.CreateTemp("", "blenderkit_params_*.json")
		if err != nil {
			TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID,
				Error: fmt.Errorf("creating params tempfile: %w", err)}
			return
		}
		paramsPath = f.Name()
		if err := json.NewEncoder(f).Encode(data.Params); err != nil {
			f.Close()
			os.Remove(paramsPath)
			TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID,
				Error: fmt.Errorf("writing params json: %w", err)}
			return
		}
		f.Close()
		defer os.Remove(paramsPath)
	}

	TaskProgressUpdateCh <- &TaskProgressUpdate{
		AppID: data.AppID, TaskID: taskID, Progress: 10, Message: "Launching Blender",
	}

	// blender --background [<blend>] --python <script> -- [<params.json>]
	cmdArgs := []string{"--background"}
	if data.BlendPath != "" {
		cmdArgs = append(cmdArgs, data.BlendPath)
	}
	cmdArgs = append(cmdArgs, "--python", scriptPath, "--")
	if paramsPath != "" {
		cmdArgs = append(cmdArgs, paramsPath)
	}

	cmd := exec.Command(data.BlenderExePath, cmdArgs...)
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID, Error: fmt.Errorf("stdout pipe: %w", err)}
		return
	}
	stderr, err := cmd.StderrPipe()
	if err != nil {
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID, Error: fmt.Errorf("stderr pipe: %w", err)}
		return
	}
	if err := cmd.Start(); err != nil {
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID, Error: fmt.Errorf("starting blender: %w", err)}
		return
	}

	// Stream stdout/stderr as task messages with non-blocking sends so a
	// flooded TaskMessageCh can't wedge cmd.Wait.
	var wg sync.WaitGroup
	wg.Add(2)
	streamReader := func(r io.Reader, prefix string) {
		defer wg.Done()
		s := bufio.NewScanner(r)
		s.Buffer(make([]byte, 64*1024), 1024*1024)
		for s.Scan() {
			update := &TaskMessageUpdate{
				AppID: data.AppID, TaskID: taskID,
				Message: statusMsg, MessageDetailed: prefix + s.Text(),
			}
			select {
			case TaskMessageCh <- update:
			default:
			}
		}
	}
	go streamReader(stdout, "[blender] ")
	go streamReader(stderr, "[blender err] ")
	wg.Wait()

	if err := cmd.Wait(); err != nil {
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID,
			Error: fmt.Errorf("blender exited with error: %w", err)}
		return
	}

	result := map[string]interface{}{}
	if data.OutputPath != "" {
		info, err := os.Stat(data.OutputPath)
		if err != nil || info.Size() == 0 {
			TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID,
				Error: errors.New("script produced no output at " + data.OutputPath)}
			return
		}
		result["file_path"] = data.OutputPath
	}
	TaskFinishCh <- &TaskFinish{
		AppID:   data.AppID,
		TaskID:  taskID,
		Message: "Script finished",
		Result:  result,
	}
}
