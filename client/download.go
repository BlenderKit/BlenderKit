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
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"

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
	// Need to populate as DownloadAssetData is sent to bg_unpack.py
	downloadData.DownloadAssetData.Resolution = downloadData.Resolution

	var rJSON map[string]interface{}
	err = json.Unmarshal(body, &rJSON)
	if err != nil {
		fmt.Println(">> Error parsing JSON:", err)
		http.Error(w, "Error parsing JSON: "+err.Error(), http.StatusBadRequest)
		return
	}

	taskID := uuid.New().String()

	go doAssetDownload(
		rJSON,
		taskID,
		downloadData.AppID,
		downloadData.Preferences.SceneID,
		downloadData.Preferences.APIKey,
		downloadData.AddonVersion,
		downloadData.PlatformVersion,
		downloadData.DownloadAssetData,
		downloadData.DownloadDirs,
		downloadData.Preferences.UnpackFiles,
		downloadData.Preferences.BinaryPath,
		downloadData.Preferences.AddonDir,
		downloadData.Preferences.AddonModuleName,
	)

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

func copyFile(src, dst string) error {
	sourceFile, err := os.Open(src)
	if err != nil {
		return err
	}
	defer sourceFile.Close()

	// Ensure the target directory exists
	if err := os.MkdirAll(filepath.Dir(dst), 0755); err != nil {
		return err
	}

	destinationFile, err := os.Create(dst)
	if err != nil {
		return err
	}
	defer destinationFile.Close()

	_, err = io.Copy(destinationFile, sourceFile)
	return err
}

func syncDirs(sourceDir, targetDir string) error {
	return filepath.Walk(sourceDir, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}

		// Skip directories directly, but ensure they exist in the target
		if info.IsDir() {
			var targetPath string
			if len(path) > len(sourceDir) {
				targetPath = filepath.Join(targetDir, path[len(sourceDir):])
			} else {
				targetPath = targetDir
			}
			return os.MkdirAll(targetPath, info.Mode())
		}

		relPath, err := filepath.Rel(sourceDir, path)
		if err != nil {
			return err
		}
		targetPath := filepath.Join(targetDir, relPath)

		// Check if the file exists in the target directory and if it needs updating
		targetInfo, err := os.Stat(targetPath)
		if os.IsNotExist(err) || info.ModTime().After(targetInfo.ModTime()) {
			if err := copyFile(path, targetPath); err != nil {
				return err
			}
		}
		return nil
	})
}

func syncDirsBidirectional(sourceDir, targetDir string) error {
	err := syncDirs(sourceDir, targetDir)
	if err != nil {
		return err
	}
	return syncDirs(targetDir, sourceDir)
}

func doAssetDownload(
	origJSON map[string]interface{},
	taskID string,
	appID int,
	sceneID string,
	apiKey string,
	addonVersion string,
	platformVersion string,
	downloadAssetData DownloadAssetData,
	downloadDirs []string,
	unpackFiles bool,
	binaryPath string,
	addonDir string,
	addonModuleName string,
) {
	TasksMux.Lock()
	task := NewTask(origJSON, appID, taskID, "asset_download")
	task.Message = "Getting download URL"
	Tasks[task.AppID][taskID] = task
	TasksMux.Unlock()

	// GET URL FOR BLEND FILE WITH CORRECT RESOLUTION
	canDownload, downloadURL, err := GetDownloadURL(sceneID, downloadAssetData.Files, downloadAssetData.Resolution, apiKey, addonVersion, platformVersion)
	if err != nil {
		TaskErrorCh <- &TaskError{
			AppID:  appID,
			TaskID: taskID,
			Error:  err}
		return
	}
	if !canDownload {
		TaskErrorCh <- &TaskError{
			AppID:  appID,
			TaskID: taskID,
			Error:  fmt.Errorf("user cannot download this file")}
		return
	}

	// EXTRACT FILENAME FROM URL
	TaskProgressUpdateCh <- &TaskProgressUpdate{
		AppID:    appID,
		TaskID:   taskID,
		Progress: 0,
		Message:  "Extracting filename",
	}
	fileName, err := ExtractFilenameFromURL(downloadURL)
	if err != nil {
		TaskErrorCh <- &TaskError{
			AppID:  appID,
			TaskID: taskID,
			Error:  err,
		}
		return
	}

	// GET FILEPATHS TO WHICH WE DOWNLOAD
	TaskProgressUpdateCh <- &TaskProgressUpdate{
		AppID:    appID,
		TaskID:   taskID,
		Progress: 0,
		Message:  "Getting filepaths",
	}
	downloadFilePaths := GetDownloadFilepaths(downloadAssetData, downloadDirs, fileName)

	// CHECK IF FILE EXISTS ON HARD DRIVE
	TaskProgressUpdateCh <- &TaskProgressUpdate{
		AppID:    appID,
		TaskID:   taskID,
		Progress: 0,
		Message:  "Checking files on disk",
	}
	existingFiles := []string{}
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
			existingFiles = append(existingFiles, filePath)
		}
	}

	action := ""
	switch len(existingFiles) {
	case 0: // No existing files -> download
		action = "download"
	case 2: // Both files exist -> skip download
		action = "place"
	case 1:
		if len(downloadFilePaths) == 2 { // One file exists, but there are two download paths -> sync the missing file
			action = "sync"
		} else if len(downloadFilePaths) == 1 { // One file exists, and there is only one download path -> skip download
			action = "place"
		}
	default: // Something unexpected happened -> delete and download
		BKLog.Printf("%s Unexpected number of existing files: %s", EmoWarning, existingFiles)
		for _, file := range downloadFilePaths {
			err := DeleteFile(file)
			if err != nil {
				BKLog.Printf("%s Error deleting file: %v", EmoWarning, err)
			}
		}
	}

	// START DOWNLOAD IF NEEDED
	fp := downloadFilePaths[0]
	if action == "download" {
		err = downloadAsset(downloadURL, fp, appID, addonVersion, platformVersion, taskID, task.Ctx)
		if err != nil {
			e := fmt.Errorf("error downloading asset: %w", err)
			TaskErrorCh <- &TaskError{
				AppID:  appID,
				TaskID: taskID,
				Error:  e,
			}
			return
		}
	} else {
		fmt.Println("PLACING THE FILE")
	}

	// UNPACKING (Only after download? By now unpack is triggered always,
	// to ensure assets that weren't unpacked get unpacked for resolution switching )
	if unpackFiles {
		// If there was no download, there's risk that the file to be unpacked
		// is only in local, but not in global directory
		if action != "download" {
			fp = existingFiles[0]
		}
		//err := UnpackAsset(fp, data, taskID)
		err := UnpackAsset(
			fp,
			taskID,
			appID,
			downloadAssetData.AssetType,
			binaryPath,
			addonDir,
			addonModuleName,
			downloadAssetData,
		)
		if err != nil {
			e := fmt.Errorf("error unpacking asset: %w", err)
			TaskErrorCh <- &TaskError{
				AppID:  appID,
				TaskID: taskID,
				Error:  e,
			}
			return
		}
	}

	// SYNC FILES IF NEEDED
	if action == "sync" || (action == "download" && len(downloadFilePaths) == 2) {
		//Synchronize both folders - we need to synchronize both sides.
		// In both folders there can be different resolutions, packed or unpacked with subfolders.

		// get directory filepaths from the downloadFilePaths
		globalAssetDir := filepath.Dir(downloadFilePaths[0])
		localAssetDir := filepath.Dir(downloadFilePaths[1])

		// Synchronize bidirectional
		err := syncDirsBidirectional(localAssetDir, globalAssetDir)
		if err != nil {
			e := fmt.Errorf("error synchronizing global and local folders: %w", err)
			TaskErrorCh <- &TaskError{
				AppID:  appID,
				TaskID: taskID,
				Error:  e,
			}
			return
		}

	}

	result := map[string]interface{}{"file_paths": downloadFilePaths, "url": downloadURL}
	TaskFinishCh <- &TaskFinish{
		AppID:   appID,
		TaskID:  taskID,
		Message: "Asset downloaded and ready",
		Result:  result,
	}
}

// UnpackAsset unpacks the downloaded asset (.blend file).
// It skips unpacking for HDRi files and returns nil immediately.
func UnpackAsset(
	blendPath string,
	taskID string,
	appID int,
	assetType string,
	binaryPath string,
	addonDir string,
	addonModuleName string,
	downloadAssetData DownloadAssetData,
	//prefs PREFS,
) error {
	if assetType == "hdr" { // Skip unpacking for HDRi files
		TaskMessageCh <- &TaskMessageUpdate{
			AppID:   appID,
			TaskID:  taskID,
			Message: "HDRi file doesn't need unpacking",
		}
		return nil
	}

	TaskMessageCh <- &TaskMessageUpdate{
		AppID:   appID,
		TaskID:  taskID,
		Message: "Unpacking files",
	}
	blenderUserScripts := filepath.Dir(filepath.Dir(addonDir)) // e.g.: /Users/username/Library/Application Support/Blender/4.1/scripts"
	unpackScriptPath := filepath.Join(addonDir, "unpack_asset_bg.py")
	dataFile := filepath.Join(os.TempDir(), "resdata.json")

	process_data := map[string]interface{}{
		"fpath":      blendPath,
		"asset_data": downloadAssetData,
		"command":    "unpack",
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
		binaryPath,
		"--background",
		"--factory-startup", // disables user preferences, addons, etc.
		"-noaudio",
		blendPath,
		"--python", unpackScriptPath,
		"--",
		dataFile,
		addonModuleName, // Legacy has it as "blenderkit", extensions have it like bl_ext.user_default.blenderkit or anything else
	)
	cmd.Env = append(os.Environ(), fmt.Sprintf("BLENDER_USER_SCRIPTS=%v", blenderUserScripts))

	// Redirect both stdout and stderr to the buffer
	var combinedOutput bytes.Buffer
	cmd.Stdout = &combinedOutput
	cmd.Stderr = &combinedOutput

	err = cmd.Run()
	color.FgGray.Printf("└> backgroung unpacking '%+v' logs:\n", cmd)
	for _, line := range strings.Split(combinedOutput.String(), "\n") {
		color.FgGray.Printf("   %s\n", line)
	}
	if err != nil {
		return err
	}

	return nil
}

func downloadAsset(url, filePath string, appID int, addonVersion, platformVersion, taskID string, ctx context.Context) error {
	TaskProgressUpdateCh <- &TaskProgressUpdate{
		AppID:    appID,
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

	req.Header = getHeaders("", *SystemID, addonVersion, platformVersion) // download needs no API key in headers
	resp, err := ClientDownloads.Do(req)
	if err != nil {
		e := DeleteFile(filePath)
		if e != nil {
			return fmt.Errorf("request failed: %w, failed to delete file: %w", err, e)
		}
		return err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		_, respString, _ := ParseFailedHTTPResponse(resp)
		err := fmt.Errorf("server returned non-OK status (%d): %s", resp.StatusCode, respString)
		e := DeleteFile(filePath)
		if e != nil {
			return fmt.Errorf("%w, failed to delete file: %w", err, e)
		}
		return err
	}

	totalLength := resp.Header.Get("Content-Length")
	if totalLength == "" {
		e := DeleteFile(filePath)
		if e != nil {
			return fmt.Errorf("request failed: %w, failed to delete file: %w", err, e)
		}
		return fmt.Errorf("Content-Length header is missing")
	}

	fileSize, err := strconv.ParseInt(totalLength, 10, 64)
	if err != nil {
		e := DeleteFile(filePath)
		if e != nil {
			return fmt.Errorf("length conversion failed: %w, failed to delete file: %w", err, e)
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
				AppID:    appID,
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
				return fmt.Errorf("%w, failed to delete file: %w", ctx.Err(), err)
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
						return fmt.Errorf("%w, failed to delete file: %w", writeErr, err)
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
					return fmt.Errorf("%w, failed to delete file: %w", readErr, err)
				}
				return readErr
			}
		}
	}
}

// should return ['/Users/ag/blenderkit_data/models/kitten_0992088b-fb84-4c69-bb6e-426272970c8b/kitten_2K_d5368c9d-092e-4319-afe1-dd765de6da01.blend']
func GetDownloadFilepaths(downloadAssetData DownloadAssetData, downloadDirs []string, filename string) []string {
	filePaths := []string{}
	filename = ServerToLocalFilename(filename, downloadAssetData.Name)
	assetDirName := GetAssetDirectoryName(downloadAssetData.Name, downloadAssetData.ID)
	for _, dir := range downloadDirs {
		assetDirPath := filepath.Join(dir, assetDirName)
		if _, err := os.Stat(assetDirPath); os.IsNotExist(err) {
			os.MkdirAll(assetDirPath, os.ModePerm)
		}
		filePath := filepath.Join(assetDirPath, filename)
		filePaths = append(filePaths, filePath)
	}

	// For Mac and Linux, we can return the file paths as they are.
	if runtime.GOOS != "windows" {
		return filePaths
	}

	// On Windows we need to check if path is not too long
	var filteredWinPaths []string
	for _, filePath := range filePaths {
		if len(filePath) < 259 {
			filteredWinPaths = append(filteredWinPaths, filePath)
		}
	}
	return filteredWinPaths
}

// Get the download URL for the asset file.
// Returns: canDownload, downloadURL, error.
func GetDownloadURL(sceneID string, files []AssetFile, resolution string, apiKey, addonVersion, platformVersion string) (bool, string, error) {
	reqData := url.Values{}
	reqData.Set("scene_uuid", sceneID)

	file, _ := GetResolutionFile(files, resolution)

	req, err := http.NewRequest("GET", file.DownloadURL, nil)
	if err != nil {
		return false, "", err
	}
	req.Header = getHeaders(apiKey, *SystemID, addonVersion, platformVersion)
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
