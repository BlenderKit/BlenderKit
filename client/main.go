package main

import (
	"bytes"
	"context"
	"crypto/tls"
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
	"sync"
	"time"

	"github.com/google/uuid"
)

const (
	Version          = "3.10.0.240115"
	ReportTimeout    = 3 * time.Minute
	OAUTH_CLIENT_ID  = "IdFRwa3SGA8eMpzhRVFMg5Ts8sPK93xBjif93x0F"
	WindowsPathLimit = 250

	// PATHS
	server_default   = "https://www.blenderkit.com"
	gravatar_dirname = "bkit_g" // directory in safeTempDir() for gravatar images

	// EMOJIS
	EmoOK            = "✅"
	EmoCancel        = "⛔"
	EmoWarning       = "⚠️ " // Needs space at the end for proper alignment, not sure why.
	EmoError         = "❌"
	EmoNetwork       = "📡"
	EmoNewConnection = "🤝"
	EmoDisconnecting = "👐"
	EmoSecure        = "🔒"
	EmoInsecure      = "🧨"
)

var (
	SystemID        *string // Unique ID of the current system (15 integers)
	PlatformVersion string
	Port            *string
	Server          *string

	CodeVerifier    string //Used for OAuth2
	CodeVerifierMux sync.Mutex

	lastReportAccess    time.Time
	lastReportAccessMux sync.Mutex

	ActiveAppsMux sync.Mutex
	ActiveApps    []int

	Tasks                map[int]map[string]*Task
	TasksMux             sync.Mutex
	AddTaskCh            chan *Task
	TaskProgressUpdateCh chan *TaskProgressUpdate
	TaskFinishCh         chan *TaskFinish
	TaskErrorCh          chan *TaskError
	TaskCancelCh         chan *TaskCancel

	ClientAPI, ClientDownloads, ClientUploads, ClientSmallThumbs, ClientBigThumbs *http.Client

	BKLog   *log.Logger
	ChanLog *log.Logger
)

func init() {
	Tasks = make(map[int]map[string]*Task)
	AddTaskCh = make(chan *Task, 100)
	TaskProgressUpdateCh = make(chan *TaskProgressUpdate, 1000)
	TaskFinishCh = make(chan *TaskFinish, 100)
	TaskErrorCh = make(chan *TaskError, 100)
	TaskCancelCh = make(chan *TaskCancel, 100)
	PlatformVersion = runtime.GOOS + " " + runtime.GOARCH + " go" + runtime.Version()

	BKLog = log.New(os.Stdout, "⬡  ", log.LstdFlags)
	ChanLog = log.New(os.Stdout, "<- ", log.LstdFlags)
}

// Endless loop to handle channels
func handleChannels() {
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
			ChanLog.Printf("%s %s (%s)\n", EmoOK, task.TaskType, task.TaskID)
		case e := <-TaskErrorCh:
			TasksMux.Lock()
			task := Tasks[e.AppID][e.TaskID]
			if task.Status == "cancelled" {
				delete(Tasks[e.AppID], e.TaskID)
				TasksMux.Unlock()
				ChanLog.Printf("%s ignored on %s (%s): %s, task in cancelled status\n", EmoCancel, task.TaskType, task.TaskID, e.Error)
				continue
			}
			task.Message = fmt.Sprintf("%v", e.Error)
			task.Status = "error"
			TasksMux.Unlock()
			ChanLog.Printf("%s in %s (%s): %v\n", EmoError, task.TaskType, task.TaskID, e.Error)
		case k := <-TaskCancelCh:
			TasksMux.Lock()
			task := Tasks[k.AppID][k.TaskID]
			task.Status = "cancelled"
			task.Cancel()
			TasksMux.Unlock()
			ChanLog.Printf("%s %s (%s), reason: %s\n", EmoCancel, task.TaskType, task.TaskID, k.Reason)
		}
	}
}

func main() {
	var err error
	Port = flag.String("port", "62485", "port to listen on")
	Server = flag.String("server", server_default, "server to connect to")
	proxy_which := flag.String("proxy_which", "SYSTEM", "proxy to use") // possible values: "SYSTEM", "NONE", "CUSTOM"
	proxy_address := flag.String("proxy_address", "", "proxy address")
	trusted_ca_certs := flag.String("trusted_ca_certs", "", "trusted CA certificates")
	ip_version := flag.String("ip_version", "BOTH", "IP version to use")
	ssl_context := flag.String("ssl_context", "DEFAULT", "SSL context to use") // possible values: "DEFAULT", "PRECONFIGURED", "DISABLED"
	SystemID = flag.String("system_id", "", "system ID")                       // Just to please the add-on
	version := flag.String("version", Version, "version of BlenderKit")
	flag.Parse()
	fmt.Print("\n\n")
	BKLog.Printf("Starting with flags port=%s server=%s version=%s system_id=%s proxy_which=%s proxy_address=%s trusted_ca_certs=%s ip_version=%s ssl_context=%s",
		*Port, *Server, *version, *SystemID, *proxy_which, *proxy_address, *trusted_ca_certs, *ip_version, *ssl_context)
	if *SystemID == "" {
		SystemID, err = fakePythonUUUIDGetNode()
		if err != nil {
			log.Fatal(err)
		}
		log.Println("Flag SystemID is empty, so guessing it:", *SystemID)
	}

	CreateHTTPClients(*proxy_address, *proxy_which, *ssl_context)
	go monitorReportAccess()
	go handleChannels()

	mux := http.NewServeMux()
	mux.HandleFunc("/", indexHandler)
	mux.HandleFunc("/shutdown", shutdownHandler)
	mux.HandleFunc("/report_blender_quit", reportBlenderQuitHandler)
	mux.HandleFunc("/report", reportHandler)
	//mux.HandleFunc("/debug", debugHandler)

	mux.HandleFunc("/cancel_download", CancelDownloadHandler)
	mux.HandleFunc("/download_asset", downloadAssetHandler)
	mux.HandleFunc("/search_asset", searchHandler)
	//mux.HandleFunc("/upload_asset", uploadAsset)

	mux.HandleFunc("/consumer/exchange/", consumerExchangeHandler)
	mux.HandleFunc("/refresh_token", RefreshTokenHandler)
	mux.HandleFunc("/code_verifier", CodeVerifierHandler)
	//mux.HandleFunc("/report_usages", reportUsagesHandler)

	mux.HandleFunc("/profiles/fetch_gravatar_image", FetchGravatarImageHandler) // TODO: Rename this to DownloadGravatarImageHandler - it is not fetching, it is downloading!
	mux.HandleFunc("/profiles/get_user_profile", GetUserProfileHandler)         // TODO: Rename this to FetchUserProfileHandler - it is not getting local data, it is fetching!

	mux.HandleFunc("/comments/get_comments", GetCommentsHandler) // TODO: Rename this to FetchCommentsHandler - it is not getting local data, it is fetching!
	mux.HandleFunc("/comments/create_comment", CreateCommentHandler)
	mux.HandleFunc("/comments/feedback_comment", FeedbackCommentHandler)
	mux.HandleFunc("/comments/mark_comment_private", MarkCommentPrivateHandler)

	mux.HandleFunc("/notifications/mark_notification_read", MarkNotificationReadHandler)

	mux.HandleFunc("/ratings/get_bookmarks", GetBookmarksHandler) // TODO: Rename this to FetchBookmarksHandler - it is not getting local data, it is fetching!
	mux.HandleFunc("/ratings/get_rating", GetRatingHandler)       // TODO: Rename this to FetchRatingHandler - it is not getting local data, it is fetching!
	mux.HandleFunc("/ratings/send_rating", SendRatingHandler)

	mux.HandleFunc("/wrappers/get_download_url", GetDownloadURLWrapper)
	mux.HandleFunc("/wrappers/blocking_file_upload", BlockingFileUploadHandler)
	mux.HandleFunc("/wrappers/blocking_file_download", BlockingFileDownloadHandler)
	mux.HandleFunc("/wrappers/blocking_request", BlockingRequestHandler)
	mux.HandleFunc("/wrappers/nonblocking_request", NonblockingRequestHandler)

	err = http.ListenAndServe(fmt.Sprintf("localhost:%s", *Port), mux)
	if err != nil {
		log.Fatalf("Failed to start server: %v\n", err)
	}
}

func monitorReportAccess() {
	for {
		time.Sleep(ReportTimeout)
		lastReportAccessMux.Lock()
		if time.Since(lastReportAccess) > ReportTimeout {
			BKLog.Printf("No /report access for %v minutes, shutting down.", ReportTimeout)
			os.Exit(0)
		}
		lastReportAccessMux.Unlock()
	}
}

func indexHandler(w http.ResponseWriter, r *http.Request) {
	pid := os.Getpid()
	fmt.Fprintf(w, "%d", pid)
}

func shutdownHandler(w http.ResponseWriter, r *http.Request) {
	go delayedExit(0.1)
	w.WriteHeader(http.StatusOK)
}

func reportHandler(w http.ResponseWriter, r *http.Request) {
	lastReportAccessMux.Lock()
	lastReportAccess = time.Now()
	lastReportAccessMux.Unlock()

	body, err := io.ReadAll(r.Body)
	if err != nil {
		http.Error(w, "Error reading request body: "+err.Error(), http.StatusInternalServerError)
		return
	}
	defer r.Body.Close()

	var data MinimalTaskData
	err = json.Unmarshal(body, &data)
	if err != nil {
		BKLog.Println("Error parsing ReportData:", err)
		http.Error(w, "Error parsing JSON: "+err.Error(), http.StatusBadRequest)
		return
	}

	taskID := uuid.New().String()
	reportTask := NewTask(nil, data.AppID, taskID, "daemon_status")
	reportTask.Finish("Daemon is running")

	TasksMux.Lock()
	if Tasks[data.AppID] == nil { // New add-on connected
		BKLog.Printf("%s New add-on connected: %d", EmoNewConnection, data.AppID)
		go FetchDisclaimer(data)
		go FetchCategories(data)
		if data.APIKey != "" {
			go FetchUnreadNotifications(data)
		}
		Tasks[data.AppID] = make(map[string]*Task)
	}

	toReport := make([]*Task, 0, len(Tasks[data.AppID]))
	toReport = append(toReport, reportTask)
	for _, task := range Tasks[data.AppID] {
		if task.AppID != data.AppID {
			continue
		}
		toReport = append(toReport, task)
		if task.Status == "finished" || task.Status == "error" {
			delete(Tasks[data.AppID], task.TaskID)
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

// MinimalTaskData is minimal data needed from add-on to schedule a task.
type MinimalTaskData struct {
	AppID  int    `json:"app_id"`  // AppID is PID of Blender in which add-on runs
	APIKey string `json:"api_key"` // Can be empty for non-logged users
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
	Result  interface{}
}

type TaskCancel struct {
	AppID  int
	TaskID string
	Reason string
}

// Task is a struct for storing a task in this Client application.
// Exported fields are used for JSON encoding/decoding and are defined in same in the add-on.
type Task struct {
	Data            interface{}        `json:"data"`             // Data for the task, should be a struct like DownloadData, SearchData, etc.
	AppID           int                `json:"app_id"`           // PID of the Blender running the add-on
	TaskID          string             `json:"task_id"`          // random UUID for the task
	TaskType        string             `json:"task_type"`        // search, download, etc.
	Message         string             `json:"message"`          // Short message for the user
	MessageDetailed string             `json:"message_detailed"` // Longer message to the console
	Progress        int                `json:"progress"`         // 0-100
	Status          string             `json:"status"`           // created, finished, error
	Result          interface{}        `json:"result"`           // Result to be used by the add-on
	Error           error              `json:"-"`                // Internal: error in the task
	Ctx             context.Context    `json:"-"`                // Internal: Context for canceling the task, use in long running functions which support it
	Cancel          context.CancelFunc `json:"-"`                // Internal: Function for canceling the task
}

func (t *Task) Finish(message string) {
	t.Status = "finished"
	t.Message = message
}
func NewTask(data interface{}, appID int, taskID, taskType string) *Task {
	if data == nil { // so it is not returned as None, but as empty dict{}
		data = make(map[string]interface{})
	}
	ctx, cancel := context.WithCancel(context.Background())
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
		Ctx:             ctx,
		Cancel:          cancel,
	}
}

func reportBlenderQuitHandler(w http.ResponseWriter, r *http.Request) {
	BKLog.Printf("%s Going to shutdown...", EmoDisconnecting)
	go delayedExit(1)
	w.WriteHeader(http.StatusOK)
}

func delayedExit(t float64) {
	time.Sleep(time.Duration(t * float64(time.Second)))
	BKLog.Println("Bye!")
	os.Exit(0)
}

type SearchData struct {
	PREFS          `json:"PREFS"`
	URLQuery       string `json:"urlquery"`
	AddonVersion   string `json:"addon_version"`
	BlenderVersion string `json:"blender_version"`
	TempDir        string `json:"tempdir"`
}

func searchHandler(w http.ResponseWriter, r *http.Request) {
	body, err := io.ReadAll(r.Body)
	if err != nil {
		http.Error(w, "Error reading search request body: "+err.Error(), http.StatusInternalServerError)
		return
	}
	defer r.Body.Close()

	var data SearchData
	err = json.Unmarshal(body, &data)
	if err != nil {
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
	go doSearch(rJSON, data, taskID)

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

// TODO: implement SearchData struct
func doSearch(rJSON map[string]interface{}, data SearchData, taskID string) {
	TasksMux.Lock()
	task := NewTask(rJSON, data.AppID, taskID, "search")
	Tasks[task.AppID][taskID] = task
	TasksMux.Unlock()

	req, err := http.NewRequest("GET", data.URLQuery, nil)
	if err != nil {
		BKLog.Println("Error creating request:", err)
		return
	}

	req.Header = getHeaders(data.PREFS.APIKey, *SystemID)
	resp, err := ClientAPI.Do(req)
	if err != nil {
		BKLog.Println("Error performing search request:", err)
		return
	}
	defer resp.Body.Close()

	var searchResult map[string]interface{}
	if err := json.NewDecoder(resp.Body).Decode(&searchResult); err != nil {
		BKLog.Println("Error decoding search response:", err)
		return
	}
	TasksMux.Lock()
	task.Result = searchResult
	task.Finish("Search results downloaded")
	TasksMux.Unlock()

	go parseThumbnails(searchResult, data)
}

func parseThumbnails(searchResults map[string]interface{}, data SearchData) {
	var smallThumbsTasks, fullThumbsTasks []*Task
	blVer, _ := StringToBlenderVersion(data.BlenderVersion)

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

		smallImgPath := filepath.Join(data.TempDir, smallImgName)
		fullImgPath := filepath.Join(data.TempDir, fullImgName)

		if smallThumbURLOK && smallImgNameErr == nil {
			taskUUID := uuid.New().String()
			taskData := DownloadThumbnailData{
				ThumbnailType: "small",
				ImagePath:     smallImgPath,
				ImageURL:      smallThumbURL,
				AssetBaseID:   assetBaseID,
				Index:         i,
			}
			task := NewTask(taskData, data.AppID, taskUUID, "thumbnail_download")
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
			taskData := DownloadThumbnailData{
				ThumbnailType: "full",
				ImagePath:     fullImgPath,
				ImageURL:      fullThumbURL,
				AssetBaseID:   assetBaseID,
				Index:         i,
			}
			task := NewTask(taskData, data.AppID, taskUUID, "thumbnail_download")
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

type DownloadThumbnailData struct {
	ThumbnailType string `json:"thumbnail_type"`
	ImagePath     string `json:"image_path"`
	ImageURL      string `json:"image_url"`
	AssetBaseID   string `json:"assetBaseId"`
	Index         int    `json:"index"`
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
	data, ok := t.Data.(DownloadThumbnailData)
	if !ok {
		TaskErrorCh <- &TaskError{AppID: t.AppID, TaskID: t.TaskID, Error: fmt.Errorf("invalid data type")}
		return
	}

	req, err := http.NewRequest("GET", data.ImageURL, nil)
	if err != nil {
		fmt.Println("Error creating request:", err)
		return
	}

	headers := getHeaders("", *SystemID)
	req.Header = headers
	resp, err := ClientBigThumbs.Do(req)
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
	file, err := os.Create(data.ImagePath)
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
	AppID        int      `json:"app_id"`
	DownloadDirs []string `json:"download_dirs"`
	AssetData    `json:"asset_data"`
	PREFS        `json:"PREFS"`
}

type Category struct {
	Name                 string     `json:"name"`
	Slug                 string     `json:"slug"`
	Active               bool       `json:"active"`
	Thumbnail            string     `json:"thumbnail"`
	ThumbnailWidth       int        `json:"thumbnailWidth"`
	ThumbnailHeight      int        `json:"thumbnailHeight"`
	Order                int        `json:"order"`
	AlternateTitle       string     `json:"alternateTitle"`
	AlternateURL         string     `json:"alternateUrl"`
	Description          string     `json:"description"`
	MetaKeywords         string     `json:"metaKeywords"`
	MetaExtra            string     `json:"metaExtra"`
	Children             []Category `json:"children"`
	AssetCount           int        `json:"assetCount"`
	AssetCountCumulative int        `json:"assetCountCumulative"`
}

// CategoriesData is a struct for storing the response from the server when fetching https://www.blenderkit.com/api/v1/categories/
type CategoriesData struct {
	Count   int        `json:"count"`
	Next    string     `json:"next"`
	Prev    string     `json:"previous"`
	Results []Category `json:"results"`
}

// Fetch categories from the server: https://www.blenderkit.com/api/v1/categories/
// API documentation: https://www.blenderkit.com/api/v1/docs/#operation/categories_list
func FetchCategories(data MinimalTaskData) {
	url := *Server + "/api/v1/categories"
	taskUUID := uuid.New().String()
	task := NewTask(nil, data.AppID, taskUUID, "categories_update")
	AddTaskCh <- task

	headers := getHeaders(data.APIKey, *SystemID)
	req, err := http.NewRequest("GET", url, nil)
	if err != nil {
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskUUID, Error: err}
		return
	}

	req.Header = headers
	resp, err := ClientAPI.Do(req)
	if err != nil {
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskUUID, Error: err}
		return
	}
	defer resp.Body.Close()

	var respData CategoriesData
	if err := json.NewDecoder(resp.Body).Decode(&respData); err != nil {
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskUUID, Error: err}
		return
	}

	fix_category_counts(respData.Results)

	TaskFinishCh <- &TaskFinish{
		AppID:   data.AppID,
		TaskID:  taskUUID,
		Message: "Categories updated",
		Result:  respData.Results,
	}
}

type Disclaimer struct {
	ValidFrom string `json:"validFrom"`
	ValidTo   string `json:"validTo"`
	Priority  int    `json:"priority"`
	Message   string `json:"message"`
	URL       string `json:"url"`
	Slug      string `json:"slug"`
}

type DisclaimerData struct {
	Count    int          `json:"count"`
	Next     string       `json:"next"`
	Previous string       `json:"previous"`
	Results  []Disclaimer `json:"results"`
}

// Fetch disclaimer from the server: https://www.blenderkit.com/api/v1/disclaimer/active/.
// API documentation:  https://www.blenderkit.com/api/v1/docs/#operation/disclaimer_active_list
func FetchDisclaimer(data MinimalTaskData) {
	url := *Server + "/api/v1/disclaimer/active/"
	taskUUID := uuid.New().String()
	task := NewTask(nil, data.AppID, taskUUID, "disclaimer")
	AddTaskCh <- task

	headers := getHeaders(data.APIKey, *SystemID)
	req, err := http.NewRequest("GET", url, nil)
	if err != nil {
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskUUID, Error: err}
		return
	}
	req.Header = headers
	resp, err := ClientAPI.Do(req)
	if err != nil {
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskUUID, Error: err}
		return
	}
	defer resp.Body.Close()

	var respData DisclaimerData
	if err := json.NewDecoder(resp.Body).Decode(&respData); err != nil {
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskUUID, Error: err}
		return
	}

	TaskFinishCh <- &TaskFinish{
		AppID:   data.AppID,
		TaskID:  taskUUID,
		Message: "Disclaimer fetched",
		Result:  respData,
	}
}

type Notification struct {
	ID          int                       `json:"id"`
	Recipient   NotificationRecipient     `json:"recipient"`
	Actor       NotificationActor         `json:"actor"`
	Target      NotificationTarget        `json:"target"`
	Verb        string                    `json:"verb"`
	ActionObj   *NotificationActionObject `json:"actionObject"`
	Level       string                    `json:"level"`
	Description string                    `json:"description"`
	Unread      bool                      `json:"unread"`
	Public      bool                      `json:"public"`
	Deleted     bool                      `json:"deleted"`
	Emailed     bool                      `json:"emailed"`
	Timestamp   string                    `json:"timestamp"`
	String      string                    `json:"string"`
}

type NotificationActor struct {
	PK               interface{} `json:"pk"` // for some reason it can be int or string
	ContentTypeName  string      `json:"contentTypeName"`
	ContentTypeModel string      `json:"contentTypeModel"`
	ContentTypeApp   string      `json:"contentTypeApp"`
	ContentTypeID    int         `json:"contentTypeId"`
	URL              string      `json:"url"`
	String           string      `json:"string"`
}

type NotificationTarget struct {
	PK               interface{} `json:"pk"` // for some reason it can be int or string
	ContentTypeName  string      `json:"contentTypeName"`
	ContentTypeModel string      `json:"contentTypeModel"`
	ContentTypeApp   string      `json:"contentTypeApp"`
	ContentTypeID    int         `json:"contentTypeId"`
	URL              string      `json:"url"`
	String           string      `json:"string"`
}

type NotificationRecipient struct {
	ID int `json:"id"`
}

type NotificationActionObject struct {
	PK               int    `json:"pk,omitempty"`
	ContentTypeName  string `json:"contentTypeName,omitempty"`
	ContentTypeModel string `json:"contentTypeModel,omitempty"`
	ContentTypeApp   string `json:"contentTypeApp,omitempty"`
	ContentTypeId    int    `json:"contentTypeId,omitempty"`
	URL              string `json:"url,omitempty"`
	String           string `json:"string,omitempty"`
}

type NotificationData struct {
	Count   int            `json:"count"`
	Next    string         `json:"next"`
	Prev    string         `json:"previous"`
	Results []Notification `json:"results"`
}

// Fetch unread notifications from the server: https://www.blenderkit.com/api/v1/notifications/unread/.
// API documentation: https://www.blenderkit.com/api/v1/docs/#operation/notifications_unread_list
func FetchUnreadNotifications(data MinimalTaskData) {
	url := *Server + "/api/v1/notifications/unread/"
	taskUUID := uuid.New().String()
	task := NewTask(nil, data.AppID, taskUUID, "notifications")
	AddTaskCh <- task

	headers := getHeaders(data.APIKey, *SystemID)
	req, err := http.NewRequest("GET", url, nil)
	if err != nil {
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskUUID, Error: err}
		return
	}
	req.Header = headers
	resp, err := ClientAPI.Do(req)
	if err != nil {
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskUUID, Error: err}
		return
	}
	defer resp.Body.Close()

	var respData NotificationData
	if err := json.NewDecoder(resp.Body).Decode(&respData); err != nil {
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskUUID, Error: err}
		return
	}

	TaskFinishCh <- &TaskFinish{
		AppID:   data.AppID,
		TaskID:  taskUUID,
		Message: "Notifications fetched",
		Result:  respData,
	}
}

type CancelDownloadData struct {
	TaskID string `json:"task_id"`
	AppID  int    `json:"app_id"`
}

func CancelDownloadHandler(w http.ResponseWriter, r *http.Request) {
	body, err := io.ReadAll(r.Body)
	if err != nil {
		http.Error(w, "Error reading request body: "+err.Error(), http.StatusInternalServerError)
		return
	}
	defer r.Body.Close()

	var data CancelDownloadData
	err = json.Unmarshal(body, &data)
	if err != nil {
		http.Error(w, "Error parsing JSON: "+err.Error(), http.StatusBadRequest)
		return
	}

	TaskCancelCh <- &TaskCancel{
		AppID:  data.AppID,
		TaskID: data.TaskID,
		Reason: "cancelled by user",
	}
	w.WriteHeader(http.StatusOK)
}

// GetDownloadURLWrapper Handle get_download_url request. This serves as a wrapper around get_download_url so this can be called from addon.
// Returns the results directly so it is a blocking on add-on side (as add-on uses blocking Requests for this).
// TODO: NEDS TESTING AND TUNING ON THE ADD-ON SIDE
func GetDownloadURLWrapper(w http.ResponseWriter, r *http.Request) {
	data := DownloadData{}
	err := json.NewDecoder(r.Body).Decode(&data)
	if err != nil {
		http.Error(w, "Error parsing JSON: "+err.Error(), http.StatusBadRequest)
		return
	}

	canDownload, URL, err := GetDownloadURL(data)
	if err != nil {
		http.Error(w, "Error getting download URL: "+err.Error(), http.StatusInternalServerError)
		return
	}

	// TODO: this is probably different implementation than in the original code, but it does not make sense to send asset_data back, it is already there!
	// needs testing and tuning on the add-on side - do not know now how to trigger this func right now
	responseJSON, err := json.Marshal(map[string]interface{}{
		"can_download": canDownload,
		"download_url": URL,
	})
	if err != nil {
		http.Error(w, "Error converting to JSON: "+err.Error(), http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	w.Write(responseJSON)
}

type FetchGravatarData struct {
	AppID        int    `json:"app_id"`
	ID           int    `json:"id"`
	Avatar128    string `json:"avatar128"` //e.g.: "/avatar-redirect/ad7c20a8-98ca-4128-9189-f727b2d1e4f3/128/"
	GravatarHash string `json:"gravatarHash"`
}

// FetchGravatarImageHandler is a handler for the /profiles/fetch_gravatar_image endpoint.
// It is used to fetch the Gravatar image for the user.
// TODO: Rename this to DownloadGravatarImageHandler - it is not fetching, it is downloading!
func FetchGravatarImageHandler(w http.ResponseWriter, r *http.Request) {
	var data FetchGravatarData
	err := json.NewDecoder(r.Body).Decode(&data)
	if err != nil {
		http.Error(w, "Error parsing JSON: "+err.Error(), http.StatusBadRequest)
		return
	}

	go FetchGravatarImage(data)
	w.WriteHeader(http.StatusOK)
}

// FetchGravatarImage is a function for fetching the Gravatar image of the creator.
// It preferes to fetch the image from the server using the Avatar128 parameter,
// but if it is not available, it tries to download it from Gravatar using gravatarHash.
func FetchGravatarImage(data FetchGravatarData) {
	var url string
	if data.Avatar128 != "" {
		url = *Server + data.Avatar128
	} else {
		url = fmt.Sprintf("https://www.gravatar.com/avatar/%v?d=404", data.GravatarHash)
	}

	taskID := uuid.New().String()
	AddTaskCh <- NewTask(data, data.AppID, taskID, "profiles/fetch_gravatar_image")

	filename := fmt.Sprintf("%d.jpg", data.ID)
	tempDir, err := GetSafeTempPath()
	if err != nil {
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID, Error: err}
		return
	}

	gravatarPath := filepath.Join(tempDir, gravatar_dirname, filename)
	exists, _, _ := FileExists(gravatarPath)
	if exists {
		TaskFinishCh <- &TaskFinish{
			AppID:   data.AppID,
			TaskID:  taskID,
			Message: "Found on disk",
			Result:  map[string]string{"gravatar_path": gravatarPath},
		}
		return
	}

	req, err := http.NewRequest("GET", url, nil)
	if err != nil {
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID, Error: err}
		return
	}

	headers := getHeaders("", *SystemID)
	req.Header = headers
	resp, err := ClientSmallThumbs.Do(req)
	if err != nil {
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID, Error: err}
		return
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		err = fmt.Errorf("error downloading gravatar image - %v: %v", resp.Status, url)
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID, Error: err}
		return
	}

	// Open the file for writing
	file, err := os.Create(gravatarPath)
	if err != nil {
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID, Error: err}
		return
	}

	// Copy the response body to the file
	if _, err := io.Copy(file, resp.Body); err != nil {
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID, Error: err}
		return
	}

	TaskFinishCh <- &TaskFinish{
		AppID:   data.AppID,
		TaskID:  taskID,
		Message: "Downloaded",
		Result:  map[string]string{"gravatar_path": gravatarPath},
	}
}

func GetUserProfileHandler(w http.ResponseWriter, r *http.Request) {
	var data MinimalTaskData
	err := json.NewDecoder(r.Body).Decode(&data)
	if err != nil {
		http.Error(w, "Error parsing JSON: "+err.Error(), http.StatusBadRequest)
		return
	}
	go GetUserProfile(data)
	w.WriteHeader(http.StatusOK)
}

func GetUserProfile(data MinimalTaskData) {
	url := *Server + "/api/v1/me/"
	taskID := uuid.New().String()
	AddTaskCh <- NewTask(data, data.AppID, taskID, "profiles/get_user_profile")

	headers := getHeaders(data.APIKey, *SystemID)
	req, err := http.NewRequest("GET", url, nil)
	if err != nil {
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID, Error: err}
		return
	}
	req.Header = headers
	resp, err := ClientAPI.Do(req)
	if err != nil {
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID, Error: err}
		return
	}
	defer resp.Body.Close()

	var respData map[string]interface{}
	if err := json.NewDecoder(resp.Body).Decode(&respData); err != nil {
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID, Error: err}
		return
	}

	TaskFinishCh <- &TaskFinish{
		AppID:   data.AppID,
		TaskID:  taskID,
		Message: "data suceessfully fetched",
		Result:  respData,
	}
}

type GetRatingData struct {
	AppID   int    `json:"app_id"`
	APIKey  string `json:"api_key"`
	AssetID string `json:"asset_id"`
}

func GetRatingHandler(w http.ResponseWriter, r *http.Request) {
	var data GetRatingData
	err := json.NewDecoder(r.Body).Decode(&data)
	if err != nil {
		http.Error(w, "Error parsing JSON: "+err.Error(), http.StatusBadRequest)
		return
	}
	go GetRating(data)
	w.WriteHeader(http.StatusOK)
}

// GetRating is a function for fetching the rating of the asset.
// Re-implements: file://daemon/daemon_ratings.py : get_rating()
func GetRating(data GetRatingData) {
	url := fmt.Sprintf("%s/api/v1/assets/%s/rating/", *Server, data.AssetID)
	taskID := uuid.New().String()
	AddTaskCh <- NewTask(data, data.AppID, taskID, "ratings/get_rating")

	req, err := http.NewRequest("GET", url, nil)
	if err != nil {
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID, Error: err}
		return
	}
	req.Header = getHeaders(data.APIKey, *SystemID)

	resp, err := ClientAPI.Do(req)
	if err != nil {
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID, Error: err}
		return
	}
	defer resp.Body.Close()

	var respData map[string]interface{}
	if err := json.NewDecoder(resp.Body).Decode(&respData); err != nil {
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID, Error: err}
		return
	}

	TaskFinishCh <- &TaskFinish{
		AppID:   data.AppID,
		TaskID:  taskID,
		Message: "Rating data obtained",
		Result:  respData,
	}
}

type SendRatingData struct {
	AppID       int    `json:"app_id"`
	APIKey      string `json:"api_key"`
	AssetID     string `json:"asset_id"`
	RatingType  string `json:"rating_type"`
	RatingValue int    `json:"rating_value"`
}

func SendRatingHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != "POST" {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}
	var data SendRatingData
	err := json.NewDecoder(r.Body).Decode(&data)
	if err != nil {
		es := fmt.Sprintf("error parsing JSON: %v", err)
		fmt.Println(es)
		http.Error(w, es, http.StatusBadRequest)
		return
	}
	go SendRating(data)
	w.WriteHeader(http.StatusOK)
}

// SendRating is a function for sending the user's rating of the asset.
// API documentation: https://www.blenderkit.com/api/v1/docs/#operation/assets_rating_update
func SendRating(data SendRatingData) {
	url := fmt.Sprintf("%s/api/v1/assets/%s/rating/%s/", *Server, data.AssetID, data.RatingType)
	taskID := uuid.New().String()
	AddTaskCh <- NewTask(data, data.AppID, taskID, "ratings/send_rating")

	reqData := map[string]interface{}{"score": data.RatingValue}
	reqBody, err := json.Marshal(reqData)
	if err != nil {
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID, Error: err}
		return
	}

	req, err := http.NewRequest("PUT", url, bytes.NewBuffer(reqBody))
	if err != nil {
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID, Error: err}
		return
	}

	req.Header = getHeaders(data.APIKey, *SystemID)
	resp, err := ClientAPI.Do(req)
	if err != nil {
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID, Error: err}
		return
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID, Error: fmt.Errorf("error rating asset - %v: %v", resp.Status, url)}
		return
	}

	var respData map[string]interface{}
	if err := json.NewDecoder(resp.Body).Decode(&respData); err != nil {
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID, Error: err}
		return
	}

	TaskFinishCh <- &TaskFinish{
		AppID:   data.AppID,
		TaskID:  taskID,
		Message: fmt.Sprintf("Rated %s=%d successfully", data.RatingType, data.RatingValue),
		Result:  respData,
	}
}

func GetBookmarksHandler(w http.ResponseWriter, r *http.Request) {
	var data MinimalTaskData
	err := json.NewDecoder(r.Body).Decode(&data)
	if err != nil {
		es := fmt.Sprintf("error parsing JSON: %v", err)
		fmt.Println(es)
		http.Error(w, es, http.StatusBadRequest)
		return
	}

	go GetBookmarks(data)
	w.WriteHeader(http.StatusOK)
}

// GetBookmarks is a function for fetching the user's bookmarks.
func GetBookmarks(data MinimalTaskData) {
	url := fmt.Sprintf("%s/api/v1/search/?query=bookmarks_rating:1", *Server)
	taskID := uuid.New().String()
	AddTaskCh <- NewTask(data, data.AppID, taskID, "ratings/get_bookmarks")

	req, err := http.NewRequest("GET", url, nil)
	if err != nil {
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID, Error: err}
		return
	}

	req.Header = getHeaders(data.APIKey, *SystemID)
	resp, err := ClientAPI.Do(req)
	if err != nil {
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID, Error: err}
		return
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID, Error: fmt.Errorf("error getting bookmarks - %v: %v", resp.Status, url)}
		return
	}

	var respData map[string]interface{}

	if err := json.NewDecoder(resp.Body).Decode(&respData); err != nil {
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID, Error: err}
		return
	}

	TaskFinishCh <- &TaskFinish{
		AppID:   data.AppID,
		TaskID:  taskID,
		Message: "Bookmarks data obtained",
		Result:  respData,
	}
}

type GetCommentsData struct {
	AppID   int    `json:"app_id"`
	APIKey  string `json:"api_key"`
	AssetID string `json:"asset_id"`
}

func GetCommentsHandler(w http.ResponseWriter, r *http.Request) {
	var data GetCommentsData
	err := json.NewDecoder(r.Body).Decode(&data)
	if err != nil {
		es := fmt.Sprintf("error parsing JSON: %v", err)
		fmt.Println(es)
		http.Error(w, es, http.StatusBadRequest)
		return
	}

	go GetComments(data)
	w.WriteHeader(http.StatusOK)
}

// GetComments fetches all comments on the given asset.
//
// API documentation: https://www.blenderkit.com/api/v1/docs/#operation/comments_read
func GetComments(data GetCommentsData) {
	url := fmt.Sprintf("%s/api/v1/comments/assets-uuidasset/%s/", *Server, data.AssetID)
	taskID := uuid.New().String()
	AddTaskCh <- NewTask(data, data.AppID, taskID, "comments/get_comments")

	req, err := http.NewRequest("GET", url, nil)
	if err != nil {
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID, Error: err}
		return
	}

	req.Header = getHeaders(data.APIKey, *SystemID)
	resp, err := ClientAPI.Do(req)
	if err != nil {
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID, Error: err}
		return
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID, Error: fmt.Errorf("error getting comments - %v: %v", resp.Status, url)}
		return
	}

	var respData map[string]interface{}
	if err := json.NewDecoder(resp.Body).Decode(&respData); err != nil {
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID, Error: err}
		return
	}

	TaskFinishCh <- &TaskFinish{
		AppID:   data.AppID,
		TaskID:  taskID,
		Message: "comments downloaded",
		Result:  respData,
	}
}

type CreateCommentData struct {
	AppID       int    `json:"app_id"`
	APIKey      string `json:"api_key"`
	AssetID     string `json:"asset_id"`
	CommentText string `json:"comment_text"`
	ReplyToID   int    `json:"reply_to_id"`
}

func CreateCommentHandler(w http.ResponseWriter, r *http.Request) {
	var data CreateCommentData
	err := json.NewDecoder(r.Body).Decode(&data)
	if err != nil {
		es := fmt.Sprintf("error parsing JSON: %v", err)
		fmt.Println(es)
		http.Error(w, es, http.StatusBadRequest)
		return
	}
	go CreateComment(data)
	w.WriteHeader(http.StatusOK)
}

type GetCommentsResponseForm struct {
	Timestamp    string `json:"timestamp"`
	SecurityHash string `json:"securityHash"`
}

type GetCommentsResponse struct {
	Form GetCommentsResponseForm `json:"form"`
}

type CommentPostData struct {
	Name         string `json:"name"`
	Email        string `json:"email"`
	URL          string `json:"url"`
	Followup     bool   `json:"followup"`
	ReplyTo      int    `json:"reply_to"`
	Honeypot     string `json:"honeypot"`
	ContentType  string `json:"content_type"`
	ObjectPK     string `json:"object_pk"`
	Timestamp    string `json:"timestamp"`
	SecurityHash string `json:"security_hash"`
	Comment      string `json:"comment"`
}

// CreateComment creates a comment on the given asset.
// It first GETs freshest comments data on the asset (from this we need Timestamp and SecurityHash for the POST request).
// It then creates a new comment through POST request.
//
// API docs GET: https://www.blenderkit.com/api/v1/docs/#operation/comments_get
//
// API docs POST: https://www.blenderkit.com/api/v1/docs/#operation/comments_comment_create
func CreateComment(data CreateCommentData) {
	get_url := fmt.Sprintf("%s/api/v1/comments/asset-comment/%s/", *Server, data.AssetID)
	post_url := fmt.Sprintf("%s/api/v1/comments/comment/", *Server)
	taskID := uuid.New().String()
	AddTaskCh <- NewTask(data, data.AppID, taskID, "comments/create_comment")

	req, err := http.NewRequest("GET", get_url, nil)
	if err != nil {
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID, Error: err}
		return
	}

	headers := getHeaders(data.APIKey, *SystemID)
	req.Header = headers
	resp, err := ClientAPI.Do(req)
	if err != nil {
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID, Error: err}
		return
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID, Error: fmt.Errorf("error getting comments - %v: %v", resp.Status, get_url)}
		return
	}

	var commentsData GetCommentsResponse
	if err := json.NewDecoder(resp.Body).Decode(&commentsData); err != nil {
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID, Error: err}
		return
	}

	uploadData := CommentPostData{
		Name:         "",
		Email:        "",
		URL:          "",
		Followup:     data.ReplyToID > 0,
		ReplyTo:      data.ReplyToID,
		Honeypot:     "",
		ContentType:  "assets.uuidasset",
		ObjectPK:     data.AssetID,
		Timestamp:    commentsData.Form.Timestamp,
		SecurityHash: commentsData.Form.SecurityHash,
		Comment:      data.CommentText,
	}
	uploadDataJSON, err := json.Marshal(uploadData)
	if err != nil {
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID, Error: err}
		return
	}

	post_req, err := http.NewRequest("POST", post_url, bytes.NewBuffer(uploadDataJSON))
	if err != nil {
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID, Error: err}
		return
	}

	post_req.Header = headers
	post_resp, err := ClientAPI.Do(post_req)
	if err != nil {
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID, Error: err}
		return
	}

	defer resp.Body.Close()

	if post_resp.StatusCode != http.StatusCreated {
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID, Error: fmt.Errorf("error creating comment - %v: %v", post_resp.Status, post_url)}
		return
	}

	var respData map[string]interface{}
	if err := json.NewDecoder(post_resp.Body).Decode(&respData); err != nil {
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID, Error: err}
		return
	}

	TaskFinishCh <- &TaskFinish{
		AppID:   data.AppID,
		TaskID:  taskID,
		Message: "Comment created",
		Result:  respData,
	}

	go GetComments(GetCommentsData{
		AppID:   data.AppID,
		APIKey:  data.APIKey,
		AssetID: data.AssetID,
	})
}

// FeedbackCommentTaskData is expected from the add-on.
type FeedbackCommentTaskData struct {
	AppID     int    `json:"app_id"`
	APIKey    string `json:"api_key"`
	AssetID   string `json:"asset_id"`
	CommentID int    `json:"comment_id"`
	Flag      string `json:"flag"`
}

// FeedbackCommentData is sent to the server.
type FeedbackCommentData struct {
	CommentID int    `json:"comment"`
	Flag      string `json:"flag"`
}

func FeedbackCommentHandler(w http.ResponseWriter, r *http.Request) {
	var data FeedbackCommentTaskData
	err := json.NewDecoder(r.Body).Decode(&data)
	if err != nil {
		es := fmt.Sprintf("error parsing JSON: %v", err)
		fmt.Println(es)
		http.Error(w, es, http.StatusBadRequest)
		return
	}
	go FeedbackComment(data)
	w.WriteHeader(http.StatusOK)
}

// FeedbackComment uploads flag on the comment to the server.
// Flag is basically like/dislike but can be also a different flag.
//
// API docs: https://www.blenderkit.com/api/v1/docs/#operation/comments_feedback_create
func FeedbackComment(data FeedbackCommentTaskData) {
	url := fmt.Sprintf("%s/api/v1/comments/feedback/", *Server)
	taskID := uuid.New().String()
	AddTaskCh <- NewTask(data, data.AppID, taskID, "comments/feedback_comment")

	upload_data := FeedbackCommentData{
		CommentID: data.CommentID,
		Flag:      data.Flag,
	}

	JSON, err := json.Marshal(upload_data)
	if err != nil {
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID, Error: err}
		return
	}

	req, err := http.NewRequest("POST", url, bytes.NewBuffer(JSON))
	if err != nil {
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID, Error: err}
		return
	}

	req.Header = getHeaders(data.APIKey, *SystemID)
	resp, err := ClientAPI.Do(req)
	if err != nil {
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID, Error: err}
		return
	}

	defer resp.Body.Close()

	if resp.StatusCode != http.StatusCreated {
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID, Error: fmt.Errorf("error creating comment feedback - %v: %v", resp.Status, url)}
		return
	}

	var respData map[string]interface{}
	if err := json.NewDecoder(resp.Body).Decode(&respData); err != nil {
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID, Error: err}
		return
	}

	TaskFinishCh <- &TaskFinish{
		AppID:   data.AppID,
		TaskID:  taskID,
		Message: "flag uploaded",
		Result:  respData,
	}
	go GetComments(GetCommentsData{
		AppID:   data.AppID,
		APIKey:  data.APIKey,
		AssetID: data.AssetID,
	})
}

// MarkCommentPrivateTaskData is expected from the add-on.
type MarkCommentPrivateTaskData struct {
	AppID     int    `json:"app_id"`
	APIKey    string `json:"api_key"`
	AssetID   string `json:"asset_id"`
	CommentID int    `json:"comment_id"`
	IsPrivate bool   `json:"is_private"`
}

// MarkCommentPrivateData is sent to the server.
type MarkCommentPrivateData struct {
	IsPrivate bool `json:"is_private"`
}

func MarkCommentPrivateHandler(w http.ResponseWriter, r *http.Request) {
	var data MarkCommentPrivateTaskData
	err := json.NewDecoder(r.Body).Decode(&data)
	if err != nil {
		es := fmt.Sprintf("error parsing JSON: %v", err)
		fmt.Println(es)
		http.Error(w, es, http.StatusBadRequest)
		return
	}
	go MarkCommentPrivate(data)
	w.WriteHeader(http.StatusOK)
}

// MarkCommentPrivate marks comment as private or public.
//
// API docs: # https://www.blenderkit.com/api/v1/docs/#operation/comments_is_private_create
func MarkCommentPrivate(data MarkCommentPrivateTaskData) {
	url := fmt.Sprintf("%s/api/v1/comments/is_private/%d/", *Server, data.CommentID)
	taskID := uuid.New().String()
	AddTaskCh <- NewTask(data, data.AppID, taskID, "comments/mark_comment_private")

	uploadData := MarkCommentPrivateData{IsPrivate: data.IsPrivate}
	JSON, err := json.Marshal(uploadData)
	if err != nil {
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID, Error: err}
		return
	}

	req, err := http.NewRequest("POST", url, bytes.NewBuffer(JSON))
	if err != nil {
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID, Error: err}
		return
	}

	req.Header = getHeaders(data.APIKey, *SystemID)
	resp, err := ClientAPI.Do(req)
	if err != nil {
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID, Error: err}
		return
	}

	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID, Error: fmt.Errorf("error creating comment feedback - %v: %v", resp.Status, url)}
		return
	}

	var respData map[string]interface{}
	if err := json.NewDecoder(resp.Body).Decode(&respData); err != nil {
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID, Error: err}
		return
	}

	TaskFinishCh <- &TaskFinish{
		AppID:   data.AppID,
		TaskID:  taskID,
		Message: "comment visibility updated",
		Result:  respData,
	}
	go GetComments(GetCommentsData{
		AppID:   data.AppID,
		APIKey:  data.APIKey,
		AssetID: data.AssetID,
	})
}

// MarkNotificationReadTaskData is expected from the add-on.
type MarkNotificationReadTaskData struct {
	AppID        int    `json:"app_id"`
	APIKey       string `json:"api_key"`
	Notification int    `json:"notification_id"`
}

func MarkNotificationReadHandler(w http.ResponseWriter, r *http.Request) {
	var data MarkNotificationReadTaskData
	err := json.NewDecoder(r.Body).Decode(&data)
	if err != nil {
		es := fmt.Sprintf("error parsing JSON: %v", err)
		fmt.Println(es)
		http.Error(w, es, http.StatusBadRequest)
		return
	}
	go MarkNotificationRead(data)
	w.WriteHeader(http.StatusOK)
}

// MarkNotificationRead marks notification as read.
//
// API docs: https://www.blenderkit.com/api/v1/docs/#operation/notifications_mark-as-read_read
func MarkNotificationRead(data MarkNotificationReadTaskData) {
	url := fmt.Sprintf("%s/api/v1/notifications/mark-as-read/%d/", *Server, data.Notification)
	taskID := uuid.New().String()
	AddTaskCh <- NewTask(data, data.AppID, taskID, "notifications/mark_notification_read")

	req, err := http.NewRequest("GET", url, nil)
	if err != nil {
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID, Error: err}
		return
	}

	req.Header = getHeaders(data.APIKey, *SystemID)
	resp, err := ClientAPI.Do(req)
	if err != nil {
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID, Error: err}
		return
	}

	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID, Error: fmt.Errorf("error creating comment feedback - %v: %v", resp.Status, url)}
		return
	}

	var respData map[string]interface{}
	if err := json.NewDecoder(resp.Body).Decode(&respData); err != nil {
		TaskErrorCh <- &TaskError{AppID: data.AppID, TaskID: taskID, Error: err}
		return
	}
	TaskFinishCh <- &TaskFinish{
		AppID:   data.AppID,
		TaskID:  taskID,
		Message: "notification marked as read",
		Result:  respData,
	}
}

// CreateHTTPClients creates HTTP clients with proxy settings, assings them to global variables.
// Handles errors gracefully - if any error occurs setting up proxy, it will just default to no proxy.
func CreateHTTPClients(proxyURL, proxyWhich, sslContext string) {
	var proxy func(*http.Request) (*url.URL, error)
	switch proxyWhich {
	case "SYSTEM":
		proxy = http.ProxyFromEnvironment
		BKLog.Printf("%s Using system proxy settings", EmoOK)
	case "CUSTOM":
		pURL, err := url.Parse(proxyURL)
		if err != nil {
			BKLog.Printf("%s Defaulting to no proxy due to - error parsing proxy URL: %v", EmoWarning, err)
		} else {
			proxy = http.ProxyURL(pURL)
			BKLog.Printf("%s Using custom proxy: %v", EmoOK, proxyURL)
		}
	case "NONE":
		BKLog.Printf("%s Using no proxy", EmoOK)
	default:
		BKLog.Printf("%s Defaulting to no proxy due to - unrecognized proxy_which parameter: %v", EmoOK, proxyWhich)
	}

	var tlsConfig *tls.Config
	switch sslContext {
	case "ENABLED":
		tlsConfig = &tls.Config{}
		BKLog.Printf("%s SSL verification is enabled", EmoSecure)
	case "DISABLED":
		tlsConfig = &tls.Config{InsecureSkipVerify: true}
		BKLog.Printf("%s SSL verification disabled, insecure!", EmoInsecure)
	default:
		tlsConfig = &tls.Config{}
		BKLog.Printf("%s Defaulting to enabled SSL verification due to - unrecognized ssl_context parameter: %v", EmoSecure, sslContext)
	}

	tAPI := http.DefaultTransport.(*http.Transport).Clone()
	tAPI.TLSClientConfig = tlsConfig
	tAPI.Proxy = proxy
	ClientAPI = &http.Client{
		Transport: tAPI,
		Timeout:   time.Minute,
	}

	tDownloads := http.DefaultTransport.(*http.Transport).Clone()
	tDownloads.TLSClientConfig = tlsConfig
	tDownloads.Proxy = proxy
	ClientDownloads = &http.Client{
		Transport: tDownloads,
		Timeout:   1 * time.Hour,
	}

	tUploads := http.DefaultTransport.(*http.Transport).Clone()
	tUploads.TLSClientConfig = tlsConfig
	tUploads.Proxy = proxy
	ClientUploads = &http.Client{
		Transport: tUploads,
		Timeout:   24 * time.Hour,
	}

	tBigThumbs := http.DefaultTransport.(*http.Transport).Clone()
	tBigThumbs.TLSClientConfig = tlsConfig
	tBigThumbs.Proxy = proxy
	ClientBigThumbs = &http.Client{
		Transport: tBigThumbs,
		Timeout:   time.Minute,
	}

	tSmallThumbs := http.DefaultTransport.(*http.Transport).Clone()
	tSmallThumbs.TLSClientConfig = tlsConfig
	tSmallThumbs.Proxy = proxy
	ClientSmallThumbs = &http.Client{
		Transport: tSmallThumbs,
		Timeout:   time.Minute,
	}
}
