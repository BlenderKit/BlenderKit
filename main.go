package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"net/http"
	"os"
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

	Tasks    map[int]map[string]*Task
	TasksMux sync.Mutex
	TasksCh  chan *Task
)

// Endless loop to handle channels
func handleChannels() {
	for {
		select {
		case task := <-TasksCh:
			TasksMux.Lock()
			Tasks[task.AppID][task.TaskID] = task
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
		if task.AppID == appID {
			continue
		}
		toReport = append(toReport, task)
		if task.Status == "finished" {
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
	fmt.Println("searchJSON:", rJSON, "appID:", appID)

	prefs, ok := rJSON["PREFS"].(map[string]interface{})
	if !ok {
		http.Error(w, "Error parsing PREFS", http.StatusInternalServerError)
		return
	}
	apiKey, ok := prefs["api_key"].(string)
	if !ok {
		http.Error(w, "Error parsing api_key", http.StatusInternalServerError)
		return
	}

	headers := getHeaders(apiKey, *SystemID)
	taskID := uuid.New().String()
	go doSearch(rJSON, appID, taskID, headers)

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

/*
searchJSON: map[
	PREFS:map[announcements_on_start:true api_key:xkILXiSE5MAjIYs6axnb0wqysdJxIM api_key_refresh:PH4f9dJfU4zL6uCsovWmul7ZCcebzc api_key_timeout:1.707241796e+09 app_id:79508 asset_popup_counter:5 auto_check_update:true binary_path:/Applications/Blender.app/Contents/MacOS/blender daemon_port:62485 debug_value:0 directory_behaviour:BOTH download_counter:105 enable_prereleases:false experimental_features:false global_dir:/Users/ag/blenderkit_data ip_version:BOTH keep_preferences:true max_assetbar_rows:1 project_subdir://assets proxy_address: proxy_which:SYSTEM resolution:2048 search_field_width:0 search_in_header:true show_on_start:false ssl_context:DEFAULT system_id:116830648666783 thumb_size:96 tips_on_start:true trusted_ca_certs: unpack_files:false updater_interval_days:10 updater_interval_months:0 welcome_operator_counter:4]
	addon_version:3.10.1
	api_key:xkILXiSE5MAjIYs6axnb0wqysdJxIM
	app_id:79508
	asset_type:model
	blender_version:4.1.0
	get_next:false
	page_size:15
	scene_uuid:<nil>
	tempdir:/var/folders/n5/zgtk48652gq_1_b8h9g2mfph0000gn/T/bktemp_ag/model_search
	urlquery:https://www.blenderkit.com/api/v1/search/?query=cat+asset_type:model+order:_score&dict_parameters=1&page_size=15&addon_version=3.10.1&blender_version=4.1.0]
*/

func doSearch(rJSON map[string]interface{}, appID int, taskID string, headers http.Header) {
	TasksMux.Lock()
	task := NewTask(rJSON, appID, taskID, "")
	Tasks[task.AppID][taskID] = task
	TasksMux.Unlock()

	urlQuery, ok := rJSON["urlquery"].(string)
	if !ok {
		log.Println("Error parsing urlquery")
		return
	}
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

	var result map[string]interface{}
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		log.Println("Error decoding search response:", err)
		return
	}
	log.Println("Search result:", result)
	task.Finish("Search results downloaded")
}

func downloadImageBatch(session *http.Client, tasks []*Task, block bool) {
	var wg sync.WaitGroup
	for _, task := range tasks {
		wg.Add(1)
		go func(t Task) {
			defer wg.Done()
			// Implement the download logic here using `session` (http.Client)
			// This could involve making HTTP GET requests for each image URL
			// specified in the `task` and handling the image data.
		}(*task)
	}

	if block {
		wg.Wait()
	}
}

/*
async def do_search(request: web.Request, task: daemon_tasks.Task):
    """Searches for results and download thumbnails.
    1. Sends search request to BlenderKit server. (Creates search task.)
    2. Reports the result to the addon. (Search task finished.)
    3. Gets small and large thumbnails. (Thumbnail tasks.)
    4. Reports paths to downloaded thumbnails. (Thumbnail task finished.)
    """
    headers = daemon_utils.get_headers(task.data["PREFS"]["api_key"])
    session = request.app["SESSION_API_REQUESTS"]
    try:
        resp_text, resp_status = None, -1
        async with session.get(task.data["urlquery"], headers=headers) as resp:
            resp_status = resp.status
            resp_text = await resp.text()
            resp.raise_for_status()
            task.result = await resp.json()
    except Exception as e:
        msg, detail = daemon_utils.extract_error_message(
            e, resp_text, resp_status, "Search failed"
        )
        return task.error(msg, message_detailed=detail)

    task.finished("Search results downloaded")
    # Post-search tasks
    small_thumbs_tasks, full_thumbs_tasks = await parse_thumbnails(task)
    await download_image_batch(request.app["SESSION_SMALL_THUMBS"], small_thumbs_tasks)
    await download_image_batch(request.app["SESSION_BIG_THUMBS"], full_thumbs_tasks)


async def download_image_batch(
    session: aiohttp.ClientSession, tsks: list[daemon_tasks.Task], block: bool = False
):
    """Download batch of images. images are tuples of file path and url."""
    atasks = []
    for task in tsks:
        task.async_task = asyncio.ensure_future(download_image(session, task))
        task.async_task.set_name(f"{task.task_type}-{task.task_id}")
        task.async_task.add_done_callback(daemon_tasks.handle_async_errors)
        atasks.append(task.async_task)

    if block is True:
        await asyncio.gather(*atasks)

*/
