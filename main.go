package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"math/rand"
	"net/http"
	"os"
	"sync"
	"time"
	// Import other packages
)

const (
	Version       = "3.10.0.240115"
	ReportTimeout = 3 * time.Minute
)

var (
	lastReportAccess time.Time
	reportAccessLock sync.Mutex
	Server           string
	taskMutex        sync.Mutex
	RunningTasks     []*Task
	ActiveAppsMux    sync.Mutex
	ActiveApps       []float64
)

func main() {
	port := flag.String("port", "62485", "port to listen on")
	server := flag.String("server", "https://www.blenderkit.com", "server to connect to")
	proxy_which := flag.String("proxy_which", "SYSTEM", "proxy to use")
	proxy_address := flag.String("proxy_address", "", "proxy address")
	trusted_ca_certs := flag.String("trusted_ca_certs", "", "trusted CA certificates")
	ip_version := flag.String("ip_version", "BOTH", "IP version to use")
	ssl_context := flag.String("ssl_context", "DEFAULT", "SSL context to use")
	system_id := flag.String("system_id", "", "system ID")
	version := flag.String("version", Version, "version of BlenderKit")
	flag.Parse()

	// PRINT ALL FLAGS
	fmt.Fprintln(os.Stdout, ">>> Starting with flags", *port, *server, *proxy_which, *proxy_address, *trusted_ca_certs, *ip_version, *ssl_context, *system_id, *version)

	// Initialize server
	dmux := DaemonMux()
	go monitorReportAccess()
	log.Printf("Starting server on port %s", *port)
	err := http.ListenAndServe("localhost:"+*port, dmux)
	if err != nil {
		log.Fatalf("Failed to start server: %v", err)
	}
}

func DaemonMux() *http.ServeMux {
	mux := http.NewServeMux()

	// Register routes
	mux.HandleFunc("/", indexHandler)
	mux.HandleFunc("/search", searchHandler)
	mux.HandleFunc("/report", reportHandler)
	mux.HandleFunc("/schedule", scheduleHandler)
	mux.HandleFunc("/report_blender_quit", reportBlenderQuitHandler)

	mux.HandleFunc("/kill_download", dummyHandler)
	mux.HandleFunc("/download_asset", dummyHandler)
	mux.HandleFunc("/search_asset", dummyHandler)
	mux.HandleFunc("/upload_asset", dummyHandler)
	mux.HandleFunc("/shutdown", dummyHandler)

	mux.HandleFunc("/consumer/exchange/", dummyHandler)
	mux.HandleFunc("/refresh_token", dummyHandler)
	mux.HandleFunc("/code_verifier", dummyHandler)
	mux.HandleFunc("/report_usages", dummyHandler)
	mux.HandleFunc("/comments/{func}", dummyHandler)
	mux.HandleFunc("/notifications/mark_notification_read", dummyHandler)

	// WRAPPERS
	mux.HandleFunc("/wrappers/get_download_url", dummyHandler)
	mux.HandleFunc("/wrappers/blocking_file_upload", dummyHandler)
	mux.HandleFunc("/wrappers/blocking_file_download", dummyHandler)
	mux.HandleFunc("/wrappers/blocking_request", dummyHandler)
	mux.HandleFunc("/wrappers/nonblocking_request", dummyHandler)

	// USER PROFILE
	mux.HandleFunc("/profiles/fetch_gravatar_image", dummyHandler)
	mux.HandleFunc("/profiles/get_user_profile", dummyHandler)

	// RATINGS
	mux.HandleFunc("/ratings/get_rating", dummyHandler)
	mux.HandleFunc("/ratings/send_rating", dummyHandler)
	mux.HandleFunc("/ratings/get_bookmarks", dummyHandler)

	// DEBUG DAEMON
	mux.HandleFunc("/debug", dummyHandler)

	return mux
}

func monitorReportAccess() {
	for {
		time.Sleep(ReportTimeout)
		reportAccessLock.Lock()
		if time.Since(lastReportAccess) > ReportTimeout {
			log.Println("No /report access for 3 minutes, shutting down.")
			os.Exit(0)
		}
		reportAccessLock.Unlock()
	}
}

func indexHandler(w http.ResponseWriter, r *http.Request) {
	pid := os.Getpid()
	fmt.Fprintf(w, "%d", pid)
}

func reportHandler(w http.ResponseWriter, r *http.Request) {
	fmt.Printf(">>> reportHandler->ActiveApps: %v\n", ActiveApps)
	taskMutex.Lock()
	defer taskMutex.Unlock()
	reportAccessLock.Lock()
	lastReportAccess = time.Now()
	reportAccessLock.Unlock()

	var requestJSON map[string]interface{}
	err := json.NewDecoder(r.Body).Decode(&requestJSON)
	if err != nil {
		http.Error(w, "Error parsing JSON", http.StatusBadRequest)
		return
	}

	appID, appIDExists := requestJSON["app_id"].(float64)
	if !appIDExists {
		http.Error(w, "Invalid or missing 'app_id' in JSON", http.StatusBadRequest)
		return
	}

	// Check if the 'app_id' is in the list of active_apps
	found := false
	for _, activeApp := range ActiveApps {
		if activeApp == appID {
			found = true
			break
		}
	}
	if !found {
		fmt.Printf("AppID not found in active apps, adding it: %f\n", appID)
		ActiveApps = append(ActiveApps, appID)
	}

	// Create a slice to store information about running tasks
	taskInfo := make([]map[string]interface{}, len(RunningTasks))

	// Capture information about each running task
	for i, task := range RunningTasks {
		taskInfo[i] = map[string]interface{}{
			"TaskID":          task.TaskID,
			"AppID":           task.AppID,
			"TaskType":        task.TaskType,
			"Message":         task.Message,
			"MessageDetailed": task.MessageDetailed,
			"Progress":        task.Progress,
			"Status":          task.Status,
		}
	}

	// Convert the task information to JSON
	responseJSON, err := json.Marshal(taskInfo)
	if err != nil {
		http.Error(w, "Error converting to JSON", http.StatusInternalServerError)
		return
	}

	// Set the response headers and write the JSON response
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	w.Write(responseJSON)
}

func searchHandler(w http.ResponseWriter, r *http.Request) {
}

func dummyHandler(w http.ResponseWriter, r *http.Request) {
	//SCHEDULE "ASYNC" TASK

	task := NewTask(nil, -1, "dummy task type", "dummy message")
	task.Status = "finished"
}

type Task struct {
	Data            map[string]interface{}
	TaskID          string
	AppID           int
	TaskType        string
	Message         string
	MessageDetailed string
	Progress        int
	Status          string
	Result          map[string]interface{}
}

func NewTask(data map[string]interface{}, appID int, taskType, message string) *Task {
	if appID == -1 {
		appID = rand.Int()
	}
	return &Task{
		Data:     data,
		TaskID:   fmt.Sprintf("%d", rand.Int()),
		AppID:    appID,
		TaskType: taskType,
		Status:   "created",
	}
}
func (t *Task) ToJSON() (string, error) {
	jsonBytes, err := json.Marshal(t)
	return string(jsonBytes), err
}
func (t *Task) Finished(message, message_detailed string) {
	t.Status = "finished"
	t.Message = message
	t.Progress = 100
}
func (t *Task) Error(message, message_detailed string) {
	t.Status = "error"
	t.Message = message
	t.MessageDetailed = message_detailed
}

func scheduleHandler(w http.ResponseWriter, r *http.Request) {
	taskMutex.Lock()
	defer taskMutex.Unlock()

	task := NewTask(nil, -1, "taskType", "message")
	RunningTasks = append(RunningTasks, task)

	go func(t *Task) {
		// Simulate a long-running task
		time.Sleep(2 * time.Minute)

		taskMutex.Lock()
		defer taskMutex.Unlock()

		// Remove the task from the runningTasks slice when done
		for i, runningTask := range RunningTasks {
			if runningTask == t {
				RunningTasks = append(RunningTasks[:i], RunningTasks[i+1:]...)
				break
			}
		}
	}(task)

	fmt.Fprintln(w, "scheduled")
}

func reportBlenderQuitHandler(w http.ResponseWriter, r *http.Request) {
	// Parse JSON request
	var data map[string]interface{}
	err := json.NewDecoder(r.Body).Decode(&data)
	if err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	fmt.Printf(">>> reportBlenderQuit->data: %v\n", data)
	appID, ok := data["app_id"].(float64)
	if !ok {
		http.Error(w, "Invalid or missing 'app_id' in JSON", http.StatusBadRequest)
		return
	}

	log.Printf("Blender quit (ID %f) was reported", appID)

	// Thread-safe access to ActiveApps slice
	ActiveAppsMux.Lock()
	indexToRemove := -1
	for i, id := range ActiveApps {
		if id == appID {
			indexToRemove = i
			break
		}
	}
	if indexToRemove != -1 {
		// Remove the appID from ActiveApps
		ActiveApps = append(ActiveApps[:indexToRemove], ActiveApps[indexToRemove+1:]...)
	}
	activeAppsLen := len(ActiveApps)
	ActiveAppsMux.Unlock()

	if activeAppsLen == 0 {
		log.Println("No more apps to serve, exiting Daemon")
		os.Exit(0)
	}

	w.WriteHeader(http.StatusOK)
	fmt.Fprint(w, "ok")
}
