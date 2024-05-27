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

package main

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"

	"github.com/google/uuid"
	"github.com/gookit/color"
)

func assetDownloadHandler(w http.ResponseWriter, r *http.Request) {
	body, err := io.ReadAll(r.Body)
	if err != nil {
		http.Error(w, "Error reading request body: "+err.Error(), http.StatusInternalServerError)
		return
	}
	// Ensure the body is closed after reading
	defer r.Body.Close()

	var downloadData DownloadData
	err = json.Unmarshal(body, &downloadData)
	if err != nil {
		fmt.Println(">> Error parsing DownloadRequest:", err)
		http.Error(w, "Error parsing JSON: "+err.Error(), http.StatusBadRequest)
		return
	}

	var rJSON map[string]interface{}
	err = json.Unmarshal(body, &rJSON)
	if err != nil {
		fmt.Println(">> Error parsing JSON:", err)
		http.Error(w, "Error parsing JSON: "+err.Error(), http.StatusBadRequest)
		return
	}

	taskID := uuid.New().String()
	go doAssetDownload(rJSON, downloadData, taskID)

	// Response to add-on
	resData := map[string]string{"task_id": taskID}
	responseJSON, err := json.Marshal(resData)
	if err != nil {
		http.Error(w, "Error converting to JSON: "+err.Error(), http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	w.Write(responseJSON)
}

func doAssetDownload(origJSON map[string]interface{}, data DownloadData, taskID string) {
	TasksMux.Lock()
	task := NewTask(origJSON, data.AppID, taskID, "asset_download")
	task.Message = "Getting download URL"
	Tasks[task.AppID][taskID] = task
	TasksMux.Unlock()

	// GET URL FOR BLEND FILE WITH CORRECT RESOLUTION
	canDownload, downloadURL, err := GetDownloadURL(data)
	if err != nil {
		TaskErrorCh <- &TaskError{
			AppID:  data.AppID,
			TaskID: taskID,
			Error:  err}
		return
	}
	if !canDownload {
		TaskErrorCh <- &TaskError{
			AppID:  data.AppID,
			TaskID: taskID,
			Error:  fmt.Errorf("user cannot download this file")}
		return
	}

	// EXTRACT FILENAME FROM URL
	TaskProgressUpdateCh <- &TaskProgressUpdate{
		AppID:    data.AppID,
		TaskID:   taskID,
		Progress: 0,
		Message:  "Extracting filename",
	}
	fileName, err := ExtractFilenameFromURL(downloadURL)
	if err != nil {
		TaskErrorCh <- &TaskError{
			AppID:  data.AppID,
			TaskID: taskID,
			Error:  err,
		}
		return
	}
	// GET FILEPATHS TO WHICH WE DOWNLOAD
	TaskProgressUpdateCh <- &TaskProgressUpdate{
		AppID:    data.AppID,
		TaskID:   taskID,
		Progress: 0,
		Message:  "Getting filepaths",
	}
	downloadFilePaths := GetDownloadFilepaths(data, fileName)

	// CHECK IF FILE EXISTS ON HARD DRIVE
	TaskProgressUpdateCh <- &TaskProgressUpdate{
		AppID:    data.AppID,
		TaskID:   taskID,
		Progress: 0,
		Message:  "Checking files on disk",
	}
	existingFiles := 0
	for _, filePath := range downloadFilePaths {
		exists, info, err := FileExists(filePath)
		if err != nil {
			if info.IsDir() {
				fmt.Println("Deleting directory:", filePath)
				err := os.RemoveAll(filePath)
				if err != nil {
					fmt.Println("Error deleting directory:", err)
				}
			} else {
				fmt.Println("Error checking if file exists:", err)
			}
			continue
		}
		if exists {
			existingFiles++
		}
	}

	action := ""
	if existingFiles == 0 { // No existing files -> download
		action = "download"
	} else if existingFiles == 2 { // Both files exist -> skip download
		action = "place"
	} else if existingFiles == 1 && len(downloadFilePaths) == 2 { // One file exists, but there are two download paths -> sync the missing file
		// TODO: sync the missing file
		action = "sync"
	} else if existingFiles == 1 && len(downloadFilePaths) == 1 { // One file exists, and there is only one download path -> skip download
		action = "place"
	} else { // Something unexpected happened -> delete and download
		log.Println("Unexpected number of existing files:", existingFiles)
		for _, file := range downloadFilePaths {
			err := DeleteFile(file)
			if err != nil {
				log.Println("Error deleting file:", err)
			}
		}
	}

	// START DOWNLOAD IF NEEDED
	fp := downloadFilePaths[0]
	if action == "download" {
		err = downloadAsset(downloadURL, fp, data, taskID, task.Ctx)
		if err != nil {
			e := fmt.Errorf("error downloading asset: %v", err)
			TaskErrorCh <- &TaskError{
				AppID:  data.AppID,
				TaskID: taskID,
				Error:  e,
			}
			return
		}
	} else {
		fmt.Println("PLACING THE FILE")
	}

	// UNPACKING
	if data.UnpackFiles {
		err := UnpackAsset(fp, data, taskID)
		if err != nil {
			e := fmt.Errorf("error unpacking asset: %v", err)
			TaskErrorCh <- &TaskError{
				AppID:  data.AppID,
				TaskID: taskID,
				Error:  e,
			}
			return
		}
	}

	result := map[string]interface{}{"file_paths": downloadFilePaths}
	TaskFinishCh <- &TaskFinish{
		AppID:   data.AppID,
		TaskID:  taskID,
		Message: "Asset downloaded and ready",
		Result:  result,
	}
}

// UnpackAsset unpacks the downloaded asset (.blend file).
// It skips unpacking for HDRi files and returns nil immediately.
func UnpackAsset(blendPath string, data DownloadData, taskID string) error {
	if data.AssetType == "hdr" { // Skip unpacking for HDRi files
		TaskMessageCh <- &TaskMessageUpdate{
			AppID:   data.AppID,
			TaskID:  taskID,
			Message: "HDRi file doesn't need unpacking",
		}
		return nil
	}

	TaskMessageCh <- &TaskMessageUpdate{
		AppID:   data.AppID,
		TaskID:  taskID,
		Message: "Unpacking files",
	}
	blenderUserScripts := filepath.Dir(filepath.Dir(data.PREFS.AddonDir)) // e.g.: /Users/username/Library/Application Support/Blender/4.1/scripts"
	unpackScriptPath := filepath.Join(data.PREFS.AddonDir, "unpack_asset_bg.py")
	dataFile := filepath.Join(os.TempDir(), "resdata.json")

	process_data := map[string]interface{}{
		"fpath":      blendPath,
		"asset_data": data.DownloadAssetData,
		"command":    "unpack",
		"PREFS":      data.PREFS,
		//"debug_value": data.PREFS.DebugValue,
	}
	jsonData, err := json.Marshal(process_data)
	if err != nil {
		return err
	}
	err = os.WriteFile(dataFile, jsonData, 0644)
	if err != nil {
		return err
	}

	cmd := exec.Command(
		data.BinaryPath,
		"--background",
		"--factory-startup", // disables user preferences, addons, etc.
		"--addons", "blenderkit",
		"-noaudio",
		blendPath,
		"--python", unpackScriptPath,
		"--",
		dataFile,
	)
	cmd.Env = append(os.Environ(), fmt.Sprintf("BLENDER_USER_SCRIPTS=%v", blenderUserScripts))
	out, err := cmd.CombinedOutput()
	color.FgGray.Println("(Background) Unpacking logs:\n", string(out))
	if err != nil {
		return err
	}

	return nil
}

func downloadAsset(url, filePath string, data DownloadData, taskID string, ctx context.Context) error {
	TaskProgressUpdateCh <- &TaskProgressUpdate{
		AppID:    data.AppID,
		TaskID:   taskID,
		Progress: 0,
		Message:  "Downloading",
	}

	file, err := os.Create(filePath)
	if err != nil {
		return err
	}
	defer file.Close()

	req, err := http.NewRequestWithContext(ctx, "GET", url, nil)
	if err != nil {
		return err
	}

	req.Header = getHeaders("", *SystemID, data.AddonVersion, data.PlatformVersion) // download needs no API key in headers
	resp, err := ClientDownloads.Do(req)
	if err != nil {
		e := DeleteFile(filePath)
		if e != nil {
			return fmt.Errorf("request failed: %v, failed to delete file: %v", err, e)
		}
		return err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		_, respString, _ := ParseFailedHTTPResponse(resp)
		err := fmt.Errorf("server returned non-OK status (%d): %s", resp.StatusCode, respString)
		e := DeleteFile(filePath)
		if e != nil {
			return fmt.Errorf("%v, failed to delete file: %v", err, e)
		}
		return err
	}

	totalLength := resp.Header.Get("Content-Length")
	if totalLength == "" {
		e := DeleteFile(filePath)
		if e != nil {
			return fmt.Errorf("request failed: %v, failed to delete file: %v", err, e)
		}
		return fmt.Errorf("Content-Length header is missing")
	}

	fileSize, err := strconv.ParseInt(totalLength, 10, 64)
	if err != nil {
		e := DeleteFile(filePath)
		if e != nil {
			return fmt.Errorf("length conversion failed: %v, failed to delete file: %v", err, e)
		}
		return err
	}

	// Setup for monitoring progress and cancellation
	sizeInMB := float64(fileSize) / 1024 / 1024
	var downloaded int64 = 0
	progress := make(chan int64)
	go func() {
		var downloadMessage string
		for p := range progress {
			progress := int(100 * p / fileSize)
			if sizeInMB < 1 { // If the size is less than 1MB, show in KB
				downloadMessage = fmt.Sprintf("Downloading %dkB (%d%%)", int(sizeInMB*1024), progress)
			} else { // If the size is not a whole number, show one decimal place
				downloadMessage = fmt.Sprintf("Downloading %.1fMB (%d%%)", sizeInMB, progress)
			}
			TaskProgressUpdateCh <- &TaskProgressUpdate{
				AppID:    data.AppID,
				TaskID:   taskID,
				Progress: progress,
				Message:  downloadMessage,
			}
		}
	}()

	buffer := make([]byte, 32*1024) // 32KB buffer
	for {
		select {
		case <-ctx.Done():
			close(progress)
			err = DeleteFile(filePath)
			if err != nil {
				return fmt.Errorf("%v, failed to delete file: %v", ctx.Err(), err)
			}
			return ctx.Err()
		default:
			n, readErr := resp.Body.Read(buffer)
			if n > 0 {
				_, writeErr := file.Write(buffer[:n])
				if writeErr != nil {
					close(progress)
					err = DeleteFile(filePath) // Clean up; ignore error from DeleteFile to focus on writeErr
					if err != nil {
						return fmt.Errorf("%v, failed to delete file: %v", writeErr, err)
					}
					return writeErr
				}
				downloaded += int64(n)
				progress <- downloaded
			}
			if readErr != nil {
				close(progress)
				if readErr == io.EOF {
					return nil // Download completed successfully
				}
				err := DeleteFile(filePath) // Clean up; ignore error from DeleteFile to focus on readErr
				if err != nil {
					return fmt.Errorf("%v, failed to delete file: %v", readErr, err)
				}
				return readErr
			}
		}
	}
}

// should return ['/Users/ag/blenderkit_data/models/kitten_0992088b-fb84-4c69-bb6e-426272970c8b/kitten_2K_d5368c9d-092e-4319-afe1-dd765de6da01.blend']
func GetDownloadFilepaths(data DownloadData, filename string) []string {
	filePaths := []string{}
	filename = ServerToLocalFilename(filename, data.DownloadAssetData.Name)
	assetFolderName := fmt.Sprintf("%s_%s", Slugify(data.DownloadAssetData.Name), data.DownloadAssetData.ID)
	for _, dir := range data.DownloadDirs {
		assetDirPath := filepath.Join(dir, assetFolderName)
		if _, err := os.Stat(assetDirPath); os.IsNotExist(err) {
			os.MkdirAll(assetDirPath, os.ModePerm)
		}
		filePath := filepath.Join(assetDirPath, filename)
		filePaths = append(filePaths, filePath)
	}
	// TODO: check on Windows if path is not too long
	return filePaths
}

// Get the download URL for the asset file.
// Returns: canDownload, downloadURL, error.
func GetDownloadURL(data DownloadData) (bool, string, error) {
	reqData := url.Values{}
	reqData.Set("scene_uuid", data.SceneID)

	file, _ := GetResolutionFile(data.Files, data.PREFS.Resolution)

	req, err := http.NewRequest("GET", file.DownloadURL, nil)
	if err != nil {
		return false, "", err
	}
	req.Header = getHeaders(data.APIKey, *SystemID, data.AddonVersion, data.PlatformVersion)
	req.URL.RawQuery = reqData.Encode()

	resp, err := ClientAPI.Do(req)
	if err != nil {
		return false, "", err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		_, respString, _ := ParseFailedHTTPResponse(resp)
		return false, "", fmt.Errorf("server returned non-OK status (%d): %s", resp.StatusCode, respString)
	}

	bodyBytes, err := io.ReadAll(resp.Body)
	if err != nil {
		return false, "", err
	}

	var respJSON map[string]interface{}
	err = json.Unmarshal(bodyBytes, &respJSON)
	if err != nil {
		return false, "", err
	}

	url, ok := respJSON["filePath"].(string)
	if !ok || url == "" {
		return false, "", fmt.Errorf("filePath is None or invalid")
	}

	return true, url, nil
}

func GetResolutionFile(files []AssetFile, targetRes string) (AssetFile, string) {
	resolutionsMap := map[string]int{
		"resolution_0_5K": 512,
		"resolution_1K":   1024,
		"resolution_2K":   2048,
		"resolution_4K":   4096,
		"resolution_8K":   8192,
	}
	var originalFile, closest AssetFile
	var targetResInt, mindist = resolutionsMap[targetRes], 100000000

	fmt.Println(">> Target resolution:", targetRes)
	for _, f := range files {
		fmt.Println(">> File type:", f.FileType)
		if f.FileType == "thumbnail" {
			continue
		}
		if f.FileType == "blend" {
			originalFile = f
			if targetRes == "ORIGINAL" {
				return f, "blend"
			}
		}

		r := strconv.Itoa(resolutionsMap[f.FileType])
		if r == targetRes {
			return f, f.FileType // exact match found, return.
		}

		// TODO: check if this works properly
		// find closest resolution if the exact match won't be found
		rval, ok := resolutionsMap[f.FileType]
		if ok && targetResInt != 0 {
			rdiff := abs(targetResInt - rval)
			if rdiff < mindist {
				closest = f
				mindist = rdiff
			}
		}
	}

	if (closest != AssetFile{}) {
		return closest, closest.FileType
	}

	return originalFile, "blend"
}
