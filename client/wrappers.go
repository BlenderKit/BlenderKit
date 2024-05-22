/*##### BEGIN GPL LICENSE BLOCK #####

  This program is free software; you can redistribute it and/or
  modify it under the terms of the GNU General Public License
  as published by the Free Software Foundation; either version 2
  of the License, or (at your option) any later version.

  This program is distributed in the hope that it will be useful,
  but WITHOUT ANY WARRANTY; without even the implied warranty of
  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
  GNU General Public License for more details.

  You should have received a copy of the GNU General Public License
  along with this program; if not, write to the Free Software Foundation,
  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.

##### END GPL LICENSE BLOCK #####*/

// Needs more focused testing.

package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"strings"

	"github.com/google/uuid"
)

// BlockingFileDownloadTaskData is expected from the add-on.
type BlockingFileDownloadTaskData struct {
	AppID    int    `json:"app_id"`
	APIKey   string `json:"api_key"`
	URL      string `json:"url"`
	Filepath string `json:"filepath"`
}

// BlockingFileDownloadHandler downloads file from a URL. It is a blocking call by design.
// It does the download of a single file, and only then returns.
func BlockingFileDownloadHandler(w http.ResponseWriter, r *http.Request) {
	var data BlockingFileDownloadTaskData
	err := json.NewDecoder(r.Body).Decode(&data)
	if err != nil {
		es := fmt.Sprintf("error parsing JSON: %v", err)
		log.Print(es)
		http.Error(w, es, http.StatusBadRequest)
		return
	}
	defer r.Body.Close()

	file, err := os.Create(data.Filepath)
	if err != nil {
		es := fmt.Sprintf("error creating file: %v", err)
		log.Print(es)
		http.Error(w, es, http.StatusInternalServerError)
		return
	}
	defer file.Close()

	req, err := http.NewRequest("GET", data.URL, nil)
	if err != nil {
		es := fmt.Sprintf("error creating request: %v", err)
		log.Print(es)
		http.Error(w, es, http.StatusInternalServerError)
		DeleteFileAndParentIfEmpty(data.Filepath)
		return
	}
	req.Header.Add("Authorization", "Bearer "+data.APIKey)

	resp, err := ClientDownloads.Do(req)
	if err != nil {
		es := fmt.Sprintf("error executing request: %v", err)
		log.Print(es)
		http.Error(w, es, http.StatusInternalServerError)
		DeleteFileAndParentIfEmpty(data.Filepath)
		return
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		es := fmt.Sprintf("server responded with status: %v", resp.Status)
		log.Print(es)
		http.Error(w, es, resp.StatusCode)
		DeleteFileAndParentIfEmpty(data.Filepath)
		return
	}

	written, err := io.Copy(file, resp.Body)
	if err != nil {
		es := fmt.Sprintf("error writing to file: %v", err)
		log.Print(es)
		http.Error(w, es, http.StatusInternalServerError)
		DeleteFileAndParentIfEmpty(data.Filepath)
		return
	}

	log.Printf("Downloaded %d bytes\n", written)
	w.WriteHeader(http.StatusOK)
	w.Write([]byte("File downloaded successfully"))
}

// BlockingRequestData represents the expected structure of the incoming request data.
type BlockingRequestData struct {
	URL     string            `json:"url"`
	Method  string            `json:"method"`
	Headers map[string]string `json:"headers"`
	JSON    json.RawMessage   `json:"json"`
}

func BlockingRequestHandler(w http.ResponseWriter, r *http.Request) {
	var data BlockingRequestData
	if err := json.NewDecoder(r.Body).Decode(&data); err != nil {
		log.Printf("Error decoding request body: %v", err)
		http.Error(w, "Invalid request body", http.StatusBadRequest)
		return
	}

	reqBody := bytes.NewReader(data.JSON)
	req, err := http.NewRequest(data.Method, data.URL, reqBody)
	if err != nil {
		log.Printf("Error creating request: %v", err)
		http.Error(w, "Failed to create request", http.StatusInternalServerError)
		return
	}

	for key, value := range data.Headers {
		req.Header.Set(key, value)
	}

	resp, err := ClientAPI.Do(req)
	if err != nil {
		log.Printf("Error making request: %v", err)
		http.Error(w, "Request failed", http.StatusInternalServerError)
		return
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		log.Printf("Error reading response body: %v", err)
		http.Error(w, "Failed to read response body", http.StatusInternalServerError)
		return
	}

	for key, value := range resp.Header {
		w.Header()[key] = value
	}
	w.WriteHeader(resp.StatusCode)
	w.Write(respBody)
}

// NonblockingRequestTaskData is expected from the add-on.
type NonblockingRequestTaskData struct {
	// Data common to all tasks.
	AppID           int    `json:"app_id"`
	SystemID        string `json:"system_id"`
	AddonVersion    string `json:"addon_version"`
	PlatformVersion string `json:"platform_version"`
	ApiKey          string `json:"api_key"`
	// Data specific to non-blocking request.
	URL      string                    `json:"url"`
	Method   string                    `json:"method"`
	Headers  map[string]string         `json:"headers"`  // Expands default headers, or overwrites them.
	Messages NonblockingRequestMessage `json:"messages"` // Error and Success messages to be reported back to the Blender UI.
	JSON     json.RawMessage           `json:"json"`
}

type NonblockingRequestMessage struct {
	Error   string `json:"error"`
	Success string `json:"success"`
}

func NonblockingRequestHandler(w http.ResponseWriter, r *http.Request) {
	var data NonblockingRequestTaskData
	err := json.NewDecoder(r.Body).Decode(&data)
	if err != nil {
		es := fmt.Sprintf("error parsing JSON: %v", err)
		fmt.Println(es)
		http.Error(w, es, http.StatusBadRequest)
		return
	}

	go NonblockingRequest(data)
	w.WriteHeader(http.StatusOK)
}

// NonblockingRequest creates a new task and adds it to the task queue.
// It makes a request to the specified URL and returns the response as result in the Task.
func NonblockingRequest(data NonblockingRequestTaskData) {
	taskID := uuid.New().String()
	AddTaskCh <- NewTask(data, data.AppID, taskID, "wrappers/nonblocking_request")

	reqBody := bytes.NewBuffer(data.JSON)
	req, err := http.NewRequest(data.Method, data.URL, reqBody)
	if err != nil {
		es := fmt.Errorf("%v: %v", data.Messages.Error, err)
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID, Error: es}
		return
	}
	req.Header = getHeaders(data.ApiKey, *SystemID, data.AddonVersion, data.PlatformVersion)
	for key, value := range data.Headers {
		req.Header.Set(key, value)
	}

	resp, err := ClientAPI.Do(req)
	if err != nil {
		es := fmt.Errorf("%v: %v", data.Messages.Error, err)
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID, Error: es}
		return
	}
	defer resp.Body.Close()

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		es := fmt.Errorf("%v: %v", data.Messages.Error, resp.Status)
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID, Error: es}
		return
	}

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		es := fmt.Errorf("%v: %v", data.Messages.Error, err)
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID, Error: es}
		return
	}

	ct := resp.Header.Get("Content-Type")
	var result interface{}
	if strings.Contains(ct, "application/json") {
		var j interface{}
		err = json.Unmarshal(respBody, &j)
		if err != nil {
			es := fmt.Errorf("%v: %v", data.Messages.Error, err)
			TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID, Error: es}
			return
		}
		result = j
	} else {
		result = string(respBody)
	}

	TaskFinishCh <- &TaskFinish{AppID: data.AppID, TaskID: taskID, Message: data.Messages.Success, Result: result}
}
