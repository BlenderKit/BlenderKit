package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"runtime"
	"sync"
	"time"

	"github.com/google/uuid"
)

const (
	Version       = "3.10.0.240115"
	ReportTimeout = 3 * time.Minute
)

var (
	SystemID        *string
	PlatformVersion string

	Server *string

	lastReportAccess     *time.Time
	lastReportAccessLock *sync.Mutex

	ActiveAppsMux sync.Mutex
	ActiveApps    []float64

	Tasks              map[int]map[string]*Task
	TasksMux           sync.Mutex
	AddTaskCh          chan *Task
	ChangeTaskStatusCh chan *TaskStatusUpdate
)

// Endless loop to handle channels
func handleChannels() {
	for {
		select {
		case task := <-AddTaskCh:
			TasksMux.Lock()
			Tasks[task.AppID][task.TaskID] = task
			TasksMux.Unlock()
		case u := <-ChangeTaskStatusCh:
			TasksMux.Lock()
			Tasks[u.AppID][u.TaskID].Status = u.Status
			if u.Progress >= 0 {
				Tasks[u.AppID][u.TaskID].Progress = u.Progress
			}
			TasksMux.Unlock()
		}
	}
}

func init() {
	Tasks = make(map[int]map[string]*Task)
	PlatformVersion = runtime.GOOS + " " + runtime.GOARCH + " go" + runtime.Version()
	fmt.Println("Platform version:", PlatformVersion)
}

func main() {
	port := flag.String("port", "62485", "port to listen on")
	Server = flag.String("server", "https://www.blenderkit.com", "server to connect to")
	proxy_which := flag.String("proxy_which", "SYSTEM", "proxy to use")
	proxy_address := flag.String("proxy_address", "", "proxy address")
	trusted_ca_certs := flag.String("trusted_ca_certs", "", "trusted CA certificates")
	ip_version := flag.String("ip_version", "BOTH", "IP version to use")
	ssl_context := flag.String("ssl_context", "DEFAULT", "SSL context to use")
	SystemID = flag.String("system_id", "", "system ID")
	version := flag.String("version", Version, "version of BlenderKit")
	flag.Parse()
	fmt.Fprintln(os.Stdout, ">>> Starting with flags", *port, *Server, *proxy_which, *proxy_address, *trusted_ca_certs, *ip_version, *ssl_context, *SystemID, *version)

	go monitorReportAccess(lastReportAccess, lastReportAccessLock)
	go handleChannels()

	mux := http.NewServeMux()
	mux.HandleFunc("/", indexHandler)
	mux.HandleFunc("/report", reportHandler)
	//mux.HandleFunc("/kill_download", killDownload)
	//mux.HandleFunc("/download_asset", downloadAsset)
	mux.HandleFunc("/search_asset", searchHandler)
	//mux.HandleFunc("/upload_asset", uploadAsset)
	//mux.HandleFunc("/shutdown", shutdown)
	mux.HandleFunc("/report_blender_quit", reportBlenderQuitHandler)
	//mux.HandleFunc("/consumer/exchange/", consumerExchange)
	//mux.HandleFunc("/refresh_token", refreshToken)
	//mux.HandleFunc("/code_verifier", codeVerifier)
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

	err := http.ListenAndServe(fmt.Sprintf("localhost:%s", *port), mux)
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
	defer TasksMux.Unlock()
	if Tasks[appID] == nil {
		Tasks[appID] = make(map[string]*Task)
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
// Progress is optional and should be set to -1 if update is not needed.
type TaskStatusUpdate struct {
	AppID    int
	TaskID   string
	Status   string
	Progress int
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

	headers := getHeaders(apiKey, *SystemID)
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
	headers := getHeaders("", *SystemID)
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
