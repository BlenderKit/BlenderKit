package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"sync"
	"time"

	"github.com/denisbrodbeck/machineid"
	"github.com/google/uuid"
)

const (
	Version          = "3.10.0.240115"
	ReportTimeout    = 3 * time.Minute
	OAUTH_CLIENT_ID  = "IdFRwa3SGA8eMpzhRVFMg5Ts8sPK93xBjif93x0F"
	WindowsPathLimit = 250
)

var (
	SystemID        string // Unique hashed ID of the current system
	PlatformVersion string
	Port            *string
	Server          *string

	CodeVerifier    string //Used for OAuth2
	CodeVerifierMux sync.Mutex

	lastReportAccess     *time.Time
	lastReportAccessLock *sync.Mutex

	ActiveAppsMux sync.Mutex
	ActiveApps    []int

	Tasks                map[int]map[string]*Task
	TasksMux             sync.Mutex
	AddTaskCh            chan *Task
	TaskProgressUpdateCh chan *TaskProgressUpdate
	TaskFinishCh         chan *TaskFinish
	TaskErrorCh          chan *TaskError
)

func init() {
	Tasks = make(map[int]map[string]*Task)
	AddTaskCh = make(chan *Task)
	TaskProgressUpdateCh = make(chan *TaskProgressUpdate)
	TaskFinishCh = make(chan *TaskFinish)
	TaskErrorCh = make(chan *TaskError)
	PlatformVersion = runtime.GOOS + " " + runtime.GOARCH + " go" + runtime.Version()

	protectedID, err := machineid.ProtectedID("myAppName")
	if err != nil {
		log.Fatal(err)
	}

	SystemID, err = fakePythonUUUIDGetNode()
	if err != nil {
		log.Fatal(err)
	}
	fmt.Println("Protected ID:", protectedID)
	fmt.Println("System ID:", SystemID)
}

// Endless loop to handle channels
func handleChannels() {
	logger := log.New(os.Stdout, "<-", log.LstdFlags)
	for {
		select {
		case task := <-AddTaskCh:
			TasksMux.Lock()
			Tasks[task.AppID][task.TaskID] = task
			TasksMux.Unlock()
		case u := <-TaskProgressUpdateCh:
			TasksMux.Lock()
			task := Tasks[u.AppID][u.TaskID]
			task.Progress = u.Progress
			if u.Message != "" {
				task.Message = u.Message
			}
			TasksMux.Unlock()
		case f := <-TaskFinishCh:
			TasksMux.Lock()
			task := Tasks[f.AppID][f.TaskID]
			task.Status = "finished"
			task.Result = f.Result
			if f.Message != "" {
				task.Message = f.Message
			}
			TasksMux.Unlock()
			logger.Printf("Finished %s (%s)\n", task.TaskType, task.TaskID)
		case e := <-TaskErrorCh:
			TasksMux.Lock()
			task := Tasks[e.AppID][e.TaskID]
			task.Message = fmt.Sprintf("%v", e.Error)
			task.Status = "error"
			TasksMux.Unlock()
			logger.Printf("Error in %s (%s): %v\n", task.TaskType, task.TaskID, e.Error)
		}
	}
}

func main() {
	Port = flag.String("port", "62485", "port to listen on")
	Server = flag.String("server", "https://www.blenderkit.com", "server to connect to")
	proxy_which := flag.String("proxy_which", "SYSTEM", "proxy to use")
	proxy_address := flag.String("proxy_address", "", "proxy address")
	trusted_ca_certs := flag.String("trusted_ca_certs", "", "trusted CA certificates")
	ip_version := flag.String("ip_version", "BOTH", "IP version to use")
	ssl_context := flag.String("ssl_context", "DEFAULT", "SSL context to use")
	flag.String("system_id", "", "system ID") // Just to please the add-on
	version := flag.String("version", Version, "version of BlenderKit")
	flag.Parse()
	fmt.Fprintln(os.Stdout, ">>> Starting with flags", *Port, *Server, *proxy_which, *proxy_address, *trusted_ca_certs, *ip_version, *ssl_context, *version)

	go monitorReportAccess(lastReportAccess, lastReportAccessLock)
	go handleChannels()

	mux := http.NewServeMux()
	mux.HandleFunc("/", indexHandler)
	mux.HandleFunc("/report", reportHandler)
	//mux.HandleFunc("/kill_download", killDownload)
	mux.HandleFunc("/download_asset", downloadAssetHandler)
	mux.HandleFunc("/search_asset", searchHandler)
	//mux.HandleFunc("/upload_asset", uploadAsset)
	//mux.HandleFunc("/shutdown", shutdown)
	mux.HandleFunc("/report_blender_quit", reportBlenderQuitHandler)

	mux.HandleFunc("/consumer/exchange/", consumerExchangeHandler)
	//mux.HandleFunc("/refresh_token", refreshToken)
	mux.HandleFunc("/code_verifier", codeVerifierHandler)
	//mux.HandleFunc("/report_usages", reportUsagesHandler)
	//mux.HandleFunc("/comments/{func}", commentsHandler) // TODO: NEEDS TO BE HANDLED SOMEHOW ELSE
	//mux.HandleFunc("/notifications/mark_notification_read", markNotificationReadHandler)

	//mux.HandleFunc("/wrappers/get_download_url", getDownloadUrlWrapper)
	//mux.HandleFunc("/wrappers/blocking_file_upload", blockingFileUploadHandler)
	//mux.HandleFunc("/wrappers/blocking_file_download", blockingFileDownloadHandler)
	//mux.HandleFunc("/wrappers/blocking_request", blockingRequestHandler)
	//mux.HandleFunc("/wrappers/nonblocking_request", nonblockingRequestHandler)

	//mux.HandleFunc("/profiles/fetch_gravatar_image", fetchGravatarImageHandler)
	//mux.HandleFunc("/profiles/get_user_profile", getUserProfileHandler)
	//mux.HandleFunc("/ratings/get_rating", getRatingHandler)
	//mux.HandleFunc("/ratings/send_rating", sendRatingHandler)
	//mux.HandleFunc("/ratings/get_bookmarks", getBookmarksHandler)
	//mux.HandleFunc("/debug", debugHandler)

	err := http.ListenAndServe(fmt.Sprintf("localhost:%s", *Port), mux)
	if err != nil {
		log.Fatalf("Failed to start server: %v\n", err)
	}
}

func monitorReportAccess(t *time.Time, l *sync.Mutex) {
	for {
		time.Sleep(ReportTimeout)
		l.Lock()
		if time.Since(*t) > ReportTimeout {
			log.Println("No /report access for 3 minutes, shutting down.")
			os.Exit(0)
		}
		l.Unlock()
	}
}

func indexHandler(w http.ResponseWriter, r *http.Request) {
	pid := os.Getpid()
	fmt.Fprintf(w, "%d", pid)
}

func reportHandler(w http.ResponseWriter, r *http.Request) {
	_, appID, err := parseRequestJSON(r)
	if err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}

	taskID := uuid.New().String()
	reportTask := NewTask(nil, appID, taskID, "daemon_status")
	reportTask.Finish("Daemon is running")
	TasksMux.Lock()
	if Tasks[appID] == nil {
		Tasks[appID] = make(map[string]*Task)
		fmt.Println("New add-on connected:", appID)
	}

	toReport := make([]*Task, 0, len(Tasks[appID]))
	toReport = append(toReport, reportTask)
	for _, task := range Tasks[appID] {
		if task.AppID != appID {
			continue
		}
		toReport = append(toReport, task)
		if task.Status == "finished" || task.Status == "error" {
			delete(Tasks[appID], task.TaskID)
		}
	}
	TasksMux.Unlock()

	responseJSON, err := json.Marshal(toReport)
	if err != nil {
		http.Error(w, "Error converting to JSON: "+err.Error(), http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	w.Write(responseJSON)
}

// TaskStatusUpdate is a struct for updating the status of a task through a channel.
// Message is optional and should be set to "" if update is not needed.
type TaskProgressUpdate struct {
	AppID    int
	TaskID   string
	Progress int
	Message  string
}

// TaskError is a struct for reporting an error in a task through a channel.
// Error will be converted to string and stored in the task's Message field.
type TaskError struct {
	AppID  int
	TaskID string
	Error  error
}

// TaskProgressUpdate is a struct for updating the progress of a task through a channel.
type TaskFinish struct {
	AppID   int
	TaskID  string
	Message string
	Result  map[string]interface{}
}

type Task struct {
	Data            map[string]interface{} `json:"data"`
	AppID           int                    `json:"app_id"`
	TaskID          string                 `json:"task_id"`
	TaskType        string                 `json:"task_type"`
	Message         string                 `json:"message"`
	MessageDetailed string                 `json:"message_detailed"`
	Progress        int                    `json:"progress"`
	Status          string                 `json:"status"` // created, finished, error
	Result          map[string]interface{} `json:"result"`
	Error           error                  `json:"-"`
}

func (t *Task) Finish(message string) {
	t.Status = "finished"
	t.Message = message
}
func NewTask(data map[string]interface{}, appID int, taskID, taskType string) *Task {
	if data == nil {
		data = make(map[string]interface{})
	}
	return &Task{
		Data:            data,
		AppID:           appID,
		TaskID:          taskID,
		TaskType:        taskType,
		Message:         "",
		MessageDetailed: "",
		Progress:        0,
		Status:          "created",
		Result:          make(map[string]interface{}),
		Error:           nil,
	}
}

func reportBlenderQuitHandler(w http.ResponseWriter, r *http.Request) {
	go delayedExit()
	w.WriteHeader(http.StatusOK)
}

func delayedExit() {
	fmt.Println("Going to die...")
	time.Sleep(3 * time.Second)
	os.Exit(0)
}

func searchHandler(w http.ResponseWriter, r *http.Request) {
	rJSON, appID, err := parseRequestJSON(r)
	if err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}

	prefs, ok := rJSON["PREFS"].(map[string]interface{})
	if !ok {
		http.Error(w, "Error parsing PREFS", http.StatusBadRequest)
		return
	}
	apiKey, ok := prefs["api_key"].(string)
	if !ok {
		http.Error(w, "Error parsing api_key", http.StatusBadRequest)
		return
	}
	urlQuery, ok := rJSON["urlquery"].(string)
	if !ok {
		http.Error(w, "Error parsing urlquery", http.StatusBadRequest)
		return
	}
	adVer, err := GetAddonVersionFromJSON(rJSON)
	if err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	blVer, err := GetBlenderVersionFromJSON(rJSON)
	if err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	tempDir, ok := rJSON["tempdir"].(string)
	if !ok {
		http.Error(w, "Error parsing tempdir", http.StatusBadRequest)
		return
	}

	headers := getHeaders(apiKey, SystemID)
	taskID := uuid.New().String()
	go doSearch(rJSON, appID, taskID, headers, urlQuery, adVer, blVer, tempDir)

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

func doSearch(rJSON map[string]interface{}, appID int, taskID string, headers http.Header, urlQuery string, adVer *AddonVersion, blVer *BlenderVersion, tempDir string) {
	TasksMux.Lock()
	task := NewTask(rJSON, appID, taskID, "search")
	Tasks[task.AppID][taskID] = task
	TasksMux.Unlock()

	client := &http.Client{}
	req, err := http.NewRequest("GET", urlQuery, nil)
	if err != nil {
		log.Println("Error creating request:", err)
		return
	}
	req.Header = headers
	fmt.Println("Search Headers:", req.Header, "URL:", req.URL.String())

	resp, err := client.Do(req)
	if err != nil {
		log.Println("Error performing search request:", err)
		return
	}
	defer resp.Body.Close()

	var searchResult map[string]interface{}
	if err := json.NewDecoder(resp.Body).Decode(&searchResult); err != nil {
		log.Println("Error decoding search response:", err)
		return
	}
	TasksMux.Lock()
	task.Result = searchResult
	task.Finish("Search results downloaded")
	TasksMux.Unlock()

	go parseThumbnails(searchResult, blVer, tempDir, appID)
}

func parseThumbnails(searchResults map[string]interface{}, blVer *BlenderVersion, tempDir string, appID int) {
	var smallThumbsTasks, fullThumbsTasks []*Task
	results, ok := searchResults["results"].([]interface{})
	if !ok {
		fmt.Println("Invalid search results:", searchResults)
		return
	}

	for i, item := range results { // TODO: Should be a function parseThumbnail() to avaid nesting
		result, ok := item.(map[string]interface{})
		if !ok {
			fmt.Println("Skipping invalid result:", item)
			continue
		}

		useWebp := false
		webpGeneratedTimestamp, ok := result["webpGeneratedTimestamp"].(float64)
		if !ok {
			fmt.Println("Invalid webpGeneratedTimestamp:", result)
		}
		if webpGeneratedTimestamp > 0 {
			useWebp = true
		}
		if blVer.Major < 3 || (blVer.Major == 3 && blVer.Minor < 4) {
			useWebp = false
		}

		assetType, ok := result["assetType"].(string)
		if !ok {
			fmt.Println("Invalid assetType:", result)
		}

		assetBaseID, ok := result["assetBaseId"].(string)
		if !ok {
			fmt.Println("Invalid assetBaseId:", result)
		}

		var smallThumbKey, fullThumbKey string
		if useWebp {
			smallThumbKey = "thumbnailSmallUrlWebp"
			if assetType == "hdr" {
				fullThumbKey = "thumbnailLargeUrlNonsquaredWebp"
			} else {
				fullThumbKey = "thumbnailMiddleUrlWebp"
			}
		} else {
			smallThumbKey = "thumbnailSmallUrl"
			if assetType == "hdr" {
				fullThumbKey = "thumbnailLargeUrlNonsquared"
			} else {
				fullThumbKey = "thumbnailMiddleUrl"
			}
		}

		smallThumbURL, smallThumbURLOK := result[smallThumbKey].(string)
		if !smallThumbURLOK {
			fmt.Printf("Invalid %s: %v\n", smallThumbKey, result)
		}

		fullThumbURL, fullThumbURLOK := result[fullThumbKey].(string)
		if !fullThumbURLOK {
			fmt.Printf("Invalid %s: %v\n", fullThumbKey, result)
		}

		smallImgName, smallImgNameErr := ExtractFilenameFromURL(smallThumbURL)
		fullImgName, fullImgNameErr := ExtractFilenameFromURL(fullThumbURL)

		smallImgPath := filepath.Join(tempDir, smallImgName)
		fullImgPath := filepath.Join(tempDir, fullImgName)

		if smallThumbURLOK && smallImgNameErr == nil {
			taskUUID := uuid.New().String()
			taskData := map[string]interface{}{
				"thumbnail_type": "small",
				"image_path":     smallImgPath,
				"image_url":      smallThumbURL,
				"assetBaseId":    assetBaseID,
				"index":          i,
			}
			task := NewTask(taskData, appID, taskUUID, "thumbnail_download")
			if _, err := os.Stat(smallImgPath); err == nil { // TODO: do not check file existence in for loop -> gotta be faster
				task.Finish("thumbnail on disk") //
			} else {
				smallThumbsTasks = append(smallThumbsTasks, task)
			}
			TasksMux.Lock()
			Tasks[task.AppID][task.TaskID] = task
			TasksMux.Unlock()
		}

		if fullThumbURLOK && fullImgNameErr == nil {
			taskUUID := uuid.New().String()
			taskData := map[string]interface{}{
				"thumbnail_type": "full",
				"image_path":     fullImgPath,
				"image_url":      fullThumbURL,
				"assetBaseId":    assetBaseID,
				"index":          i,
			}
			task := NewTask(taskData, appID, taskUUID, "thumbnail_download")
			if _, err := os.Stat(fullImgPath); err == nil {
				task.Finish("thumbnail on disk")
			} else {
				fullThumbsTasks = append(fullThumbsTasks, task)
			}
			TasksMux.Lock()
			Tasks[task.AppID][task.TaskID] = task
			TasksMux.Unlock()
		}
	}
	go downloadImageBatch(smallThumbsTasks, true)
	go downloadImageBatch(fullThumbsTasks, true)
}

func downloadImageBatch(tasks []*Task, block bool) {
	wg := new(sync.WaitGroup)
	for _, task := range tasks {
		wg.Add(1)
		go DownloadThumbnail(task, wg)
	}
	if block {
		wg.Wait()
	}
}

func DownloadThumbnail(t *Task, wg *sync.WaitGroup) {
	defer wg.Done()
	imgURL, ok := t.Data["image_url"].(string)
	if !ok {
		fmt.Println("Invalid image_url:", t.Data)
		return
	}
	imgPath, ok := t.Data["image_path"].(string)
	if !ok {
		fmt.Println("Invalid image_path:", t.Data)
		return
	}

	req, err := http.NewRequest("GET", imgURL, nil)
	if err != nil {
		fmt.Println("Error creating request:", err)
		return
	}
	headers := getHeaders("", SystemID)
	req.Header = headers

	client := &http.Client{}
	resp, err := client.Do(req)
	if err != nil {
		TasksMux.Lock()
		t.Message = "Error performing request to download thumbnail"
		t.Status = "error"
		TasksMux.Unlock()
		return
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		TasksMux.Lock()
		t.Message = "Error downloading thumbnail"
		t.Status = "error"
		TasksMux.Unlock()
		return
	}

	// Open the file for writing
	file, err := os.Create(imgPath)
	if err != nil {
		TasksMux.Lock()
		t.Message = "Error creating file for thumbnail"
		t.Status = "error"
		TasksMux.Unlock()
		return
	}
	defer file.Close()

	// Copy the response body to the file
	if _, err := io.Copy(file, resp.Body); err != nil {
		TasksMux.Lock()
		t.Message = "Error copying thumbnail response body to file"
		t.Status = "error"
		TasksMux.Unlock()
		return
	}
	TasksMux.Lock()
	t.Finish("thumbnail downloaded")
	TasksMux.Unlock()
}

func downloadAssetHandler(w http.ResponseWriter, r *http.Request) {
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
		fmt.Println(">>> Error parsing DownloadRequest:", err)
		http.Error(w, "Error parsing JSON: "+err.Error(), http.StatusBadRequest)
		return
	}

	var rJSON map[string]interface{}
	err = json.Unmarshal(body, &rJSON)
	if err != nil {
		fmt.Println(">>> Error parsing JSON:", err)
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
	if action == "download" {
		fp := downloadFilePaths[0]
		err = downloadAsset(downloadURL, fp, data, taskID)
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

	if data.UnpackFiles {
		// TODO: UNPACK FILE
	}

	result := map[string]interface{}{"file_paths": downloadFilePaths}
	TaskFinishCh <- &TaskFinish{
		AppID:   data.AppID,
		TaskID:  taskID,
		Message: "Asset downloaded and ready",
		Result:  result,
	}
}

func downloadAsset(url, filePath string, data DownloadData, taskID string) error {
	file, err := os.Create(filePath)
	if err != nil {
		return err
	}
	defer file.Close()

	client := &http.Client{}
	req, err := http.NewRequest("GET", url, nil)
	if err != nil {
		return err
	}

	req.Header = getHeaders("", SystemID) // download needs no API key in headers
	resp, err := client.Do(req)
	if err != nil {
		e := DeleteFile(filePath)
		if e != nil {
			return fmt.Errorf("request failed: %v, failed to delete file: %v", err, e)
		}
		return err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		err := fmt.Errorf("server returned non-OK status: %d", resp.StatusCode)
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

	fileSize, err := strconv.Atoi(totalLength)
	if err != nil {
		e := DeleteFile(filePath)
		if e != nil {
			return fmt.Errorf("length conversion failed: %v, failed to delete file: %v", err, e)
		}
		return err
	}

	sizeInMB := float64(fileSize) / 1024 / 1024
	downloadMessage := fmt.Sprintf("Downloading %.2fMB", sizeInMB)

	var downloaded int
	const chunkSize = 4096 * 32
	buffer := make([]byte, chunkSize)
	for {
		n, err := resp.Body.Read(buffer)
		if n > 0 {
			downloaded += n
			progress := int(100 * downloaded / fileSize)
			TaskProgressUpdateCh <- &TaskProgressUpdate{
				AppID:    data.AppID,
				TaskID:   taskID,
				Progress: progress,
				Message:  downloadMessage,
			}

			_, writeErr := file.Write(buffer[:n])
			if writeErr != nil {
				e := DeleteFile(filePath)
				if e != nil {
					return fmt.Errorf("writing file failed: %v, failed to delete file: %v", err, e)
				}
				return writeErr
			}
		}
		if err != nil {
			if err == io.EOF {
				return nil // end of file reached, download completed
			}
			e := DeleteFile(filePath)
			if e != nil {
				return fmt.Errorf("reading response body failed: %v, failed to delete file: %v", err, e)
			}
			return err
		}
	}
}

// should return ['/Users/ag/blenderkit_data/models/kitten_0992088b-fb84-4c69-bb6e-426272970c8b/kitten_2K_d5368c9d-092e-4319-afe1-dd765de6da01.blend']
func GetDownloadFilepaths(data DownloadData, filename string) []string {
	filePaths := []string{}
	filename = ServerToLocalFilename(filename, data.AssetData.Name)
	assetFolderName := fmt.Sprintf("%s_%s", Slugify(data.AssetData.Name), data.AssetData.ID)
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

type PREFS struct {
	APIKey        string `json:"api_key"`
	APIKeyRefres  string `json:"api_key_refresh"`
	APIKeyTimeout int    `json:"api_key_timeout"`
	SceneID       string `json:"scene_id"`
	AppID         int    `json:"app_id"`
	BinaryPath    string `json:"binary_path"`
	SystemID      string `json:"system_id"`
	GlobalDir     string `json:"global_dir"`
	ProjectSubdir string `json:"project_subdir"`
	UnpackFiles   bool   `json:"unpack_files"`
	Resolution    string `json:"resolution"` // "ORIGINAL", "resolution_0_5K", "resolution_1K", "resolution_2K", "resolution_4K", "resolution_8K"
}

type File struct {
	Created     string `json:"created"`
	DownloadURL string `json:"downloadUrl"`
	FileType    string `json:"fileType"`
}

type AssetData struct {
	Name                 string `json:"name"`
	ID                   string `json:"id"`
	AvailableResolutions []int  `json:"available_resolutions"`
	Files                []File `json:"files"`
}

type DownloadData struct {
	DownloadDirs []string `json:"download_dirs"`
	AssetData    `json:"asset_data"`
	PREFS        `json:"PREFS"`
}

func GetDownloadURL(data DownloadData) (bool, string, error) {
	reqData := url.Values{}
	reqData.Set("scene_uuid", data.SceneID)

	file, _ := GetResolutionFile(data.Files, data.Resolution)

	client := &http.Client{}
	req, err := http.NewRequest("GET", file.DownloadURL, nil)
	if err != nil {
		return false, "", err
	}
	req.Header = getHeaders(data.APIKey, SystemID)
	req.URL.RawQuery = reqData.Encode()

	resp, err := client.Do(req)
	if err != nil {
		return false, "", err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return false, "", fmt.Errorf("server returned non-OK status: %d", resp.StatusCode)
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

func GetResolutionFile(files []File, targetRes string) (File, string) {
	resolutionsMap := map[string]int{
		"resolution_0_5K": 512,
		"resolution_1K":   1024,
		"resolution_2K":   2048,
		"resolution_4K":   4096,
		"resolution_8K":   8192,
	}
	var originalFile, closest File
	var targetResInt, mindist = resolutionsMap[targetRes], 100000000

	fmt.Println(">>> Target resolution:", targetRes)
	for _, f := range files {
		fmt.Println(">>> File type:", f.FileType)
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

	if (closest != File{}) {
		return closest, closest.FileType
	}

	return originalFile, "blend"
}

// Helper function to calculate absolute value.
func abs(x int) int {
	if x < 0 {
		return -x
	}
	return x
}
