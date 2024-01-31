package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"net/http"
	"os"
	"sync"
	"time"

	"github.com/google/uuid"
)

const (
	Version       = "3.10.0.240115"
	ReportTimeout = 3 * time.Minute
)

var (
	Server *string

	lastReportAccess     *time.Time
	lastReportAccessLock *sync.Mutex

	ActiveAppsMux sync.Mutex
	ActiveApps    []float64

	Tasks    []*Task
	TasksMux sync.Mutex
	TasksCh  chan *Task
)

// Endless loop to handle channels
func handleChannels() {
	for {
		select {
		case task := <-TasksCh:
			TasksMux.Lock()
			Tasks = append(Tasks, task)
			TasksMux.Unlock()
		}
	}
}

func main() {
	port := flag.String("port", "62485", "port to listen on")
	Server = flag.String("server", "https://www.blenderkit.com", "server to connect to")
	proxy_which := flag.String("proxy_which", "SYSTEM", "proxy to use")
	proxy_address := flag.String("proxy_address", "", "proxy address")
	trusted_ca_certs := flag.String("trusted_ca_certs", "", "trusted CA certificates")
	ip_version := flag.String("ip_version", "BOTH", "IP version to use")
	ssl_context := flag.String("ssl_context", "DEFAULT", "SSL context to use")
	system_id := flag.String("system_id", "", "system ID")
	version := flag.String("version", Version, "version of BlenderKit")
	flag.Parse()
	fmt.Fprintln(os.Stdout, ">>> Starting with flags", *port, *Server, *proxy_which, *proxy_address, *trusted_ca_certs, *ip_version, *ssl_context, *system_id, *version)

	go monitorReportAccess(lastReportAccess, lastReportAccessLock)
	go handleChannels()

	mux := http.NewServeMux()
	mux.HandleFunc("/", indexHandler)
	mux.HandleFunc("/search", searchHandler)
	mux.HandleFunc("/report_blender_quit", reportBlenderQuitHandler)
	mux.HandleFunc("/report", reportHandler)

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

func searchHandler(w http.ResponseWriter, r *http.Request) {
}

func reportHandler(w http.ResponseWriter, r *http.Request) {
	var requestJSON map[string]interface{}
	if err := json.NewDecoder(r.Body).Decode(&requestJSON); err != nil {
		http.Error(w, "Error parsing JSON: "+err.Error(), http.StatusBadRequest)
		return
	}
	appIDFloat, appIDExists := requestJSON["app_id"].(float64)
	if !appIDExists {
		http.Error(w, "Invalid or missing 'app_id' in JSON", http.StatusBadRequest)
		return
	}
	appID := int(appIDFloat)

	TasksMux.Lock()
	tasks := Tasks
	defer TasksMux.Unlock()

	daemonReportTask := NewTask(make(map[string]interface{}), appID, "daemon_status", "")
	daemonReportTask.Result = make(map[string]interface{})
	tasks = append(tasks, daemonReportTask)

	responseJSON, err := json.Marshal(tasks)
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
	Status          string                 `json:"status"`
	Result          map[string]interface{} `json:"result"`
	Error           error                  `json:"-"`
}

func NewTask(data map[string]interface{}, appID int, taskType, message string) *Task {
	taskID := uuid.New().String()
	return &Task{
		Data:     data,
		AppID:    appID,
		TaskID:   taskID,
		TaskType: taskType,
		Status:   "created",
		Progress: 0,
		Message:  message,
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
