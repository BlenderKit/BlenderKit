package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"reflect"
	"sort"
	"strings"
	"sync"
	"testing"
	"time"
)

// mockHttpResponse creates a new http.Response from the given body and status code.
func mockHTTPResponse(body string, statusCode int) *http.Response {
	return &http.Response{
		StatusCode: statusCode,
		Body:       io.NopCloser(bytes.NewBufferString(body)),
		Request: &http.Request{
			URL: &url.URL{
				Scheme: "http",
				Host:   "example.com",
			},
		},
	}
}

func TestParseFailedHTTPResponse(t *testing.T) {
	tests := []struct {
		name       string
		response   *http.Response
		wantErr    bool
		errMessage string
	}{
		{
			name:     "Valid JSON with string detail",
			response: mockHTTPResponse(`{"detail": "scene_uuid is not a valid UUID", "statusCode": 403}`, 403),
			wantErr:  false,
		},
		{
			name:     "Valid JSON with map detail",
			response: mockHTTPResponse(`{"detail":{"thumbnail": "Invalid image format. Only PNG and JPEG are supported."},"statusCode": 400}`, 400),
			wantErr:  false,
		},
		{
			name:       "Invalid JSON",
			response:   mockHTTPResponse("invalid json", 400),
			wantErr:    true,
			errMessage: "invalid json",
		},
		{
			name:     "Valid JSON with complex structure",
			response: mockHTTPResponse(`{"detail": "Limit of private storage exceeded. Limit is 1.0 B, 1.0 B is remaining. You tried to add 7.0 B", "addedSize": 7, "addedSizeFmt": "7.0 B", "code": "private_quota_limit", "freeQuota": 1, "freeQuotaFmt": "1.0 B", "quota": 1, "quotaFmt": "1.0 B"}`, 400),
			wantErr:  false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			JSON, bodyString, err := ParseFailedHTTPResponse(tt.response)
			if (err != nil) != tt.wantErr {
				t.Errorf("ParseFailedHTTPResponse() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if tt.wantErr && !strings.Contains(err.Error(), tt.errMessage) {
				t.Errorf("ParseFailedHTTPResponse() error = %v, wantErr containing %s", err, tt.errMessage)
			}
			if tt.wantErr {
				return
			}
			if !json.Valid(JSON) {
				t.Errorf("ParseFailedHTTPResponse() got invalid JSON")
			}
			if bodyString == "" {
				t.Errorf("ParseFailedHTTPResponse() got empty bodyString")
			}
		})
	}
}

func TestDictToParams(t *testing.T) {
	tests := []struct {
		name     string
		inputs   map[string]interface{}
		expected []map[string]string
	}{
		{
			name:     "Empty input",
			inputs:   map[string]interface{}{},
			expected: []map[string]string{},
		},
		{
			name: "String input",
			inputs: map[string]interface{}{
				"key": "value",
			},
			expected: []map[string]string{
				{"parameterType": "key", "value": "value"},
			},
		},
		{
			name: "String slice input",
			inputs: map[string]interface{}{
				"key": []string{"value1", "value2"},
			},
			expected: []map[string]string{
				{"parameterType": "key", "value": "value1,value2"},
			},
		},
		{
			name: "Bool input",
			inputs: map[string]interface{}{
				"key": true,
			},
			expected: []map[string]string{
				{"parameterType": "key", "value": "true"},
			},
		},
		{
			name: "Int input",
			inputs: map[string]interface{}{
				"int": int(42),
			},
			expected: []map[string]string{
				{"parameterType": "int", "value": "42"},
			},
		},
		{
			name: "Int input - negative",
			inputs: map[string]interface{}{
				"int32": int32(-42 * 1000 * 1000),
			},
			expected: []map[string]string{
				{"parameterType": "int32", "value": "-42000000"},
			},
		},
		{
			name: "Int input - huge",
			inputs: map[string]interface{}{
				"int64": int(42 * 1000 * 1000 * 1000 * 1000 * 1000),
			},
			expected: []map[string]string{
				{"parameterType": "int64", "value": "42000000000000000"},
			},
		},
		{
			name: "Float inputs",
			inputs: map[string]interface{}{
				"float32": float32(-3.000),
			},
			expected: []map[string]string{
				{"parameterType": "float32", "value": "-3"},
			},
		},
		{
			name: "Float input - with trailing zeros",
			inputs: map[string]interface{}{
				"float64": float64(3.123456789000),
			},
			expected: []map[string]string{
				{"parameterType": "float64", "value": "3.123456789"},
			},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := DictToParams(tt.inputs)
			if !reflect.DeepEqual(result, tt.expected) {
				t.Errorf("DictToParams(%v) = %v, expected %v", tt.inputs, result, tt.expected)
			}
		})
	}
}

func TestGetAvailableSoftwares(t *testing.T) {
	AvailableSoftwares = make(map[int]Software)
	AvailableSoftwaresMux = sync.Mutex{}

	tests := []struct {
		name          string
		softwareMap   map[int]Software
		expectedCount int
	}{
		{
			name:          "Empty map",
			softwareMap:   map[int]Software{},
			expectedCount: 0,
		},
		{
			name: "Map with one software",
			softwareMap: map[int]Software{
				1001: {AppID: 1001, Name: "Blender", Version: "4.2.1", AddonVersion: "3.13.0"},
			},
			expectedCount: 1,
		},
		{
			name: "Map with multiple softwares",
			softwareMap: map[int]Software{
				1001: {AppID: 1001, Name: "Blender", Version: "4.2.1", AddonVersion: "3.13.0"},
				2222: {AppID: 2222, Name: "Godot", Version: "4.3.0", AddonVersion: "0.1.0"},
			},
			expectedCount: 2,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			AvailableSoftwaresMux.Lock()
			AvailableSoftwares = tt.softwareMap
			AvailableSoftwaresMux.Unlock()

			result := GetAvailableSoftwares()

			if len(result) != tt.expectedCount {
				t.Errorf("Expected %d softwares, got %d", tt.expectedCount, len(result))
			}

			for _, software := range result {
				if _, exists := tt.softwareMap[software.AppID]; !exists {
					t.Errorf("Software with AppID %d not found in original map", software.AppID)
				}
			}
		})
	}

	// clean global variables after the test
	AvailableSoftwares = make(map[int]Software)
	AvailableSoftwaresMux = sync.Mutex{}
}

func TestUpdateAvailableSoftware(t *testing.T) {
	AvailableSoftwares = make(map[int]Software)
	AvailableSoftwaresMux = sync.Mutex{}

	tests := []struct {
		name                   string
		inputSoftware          Software
		expectedNew            bool
		expectedSoftwaresCount int
		expectedAppID          int
		expectedName           string
		expectedAssetsPath     string
	}{
		{
			name:                   "New Blender connected",
			inputSoftware:          Software{AppID: 2422, Name: "Blender", Version: "4.2.2", AddonVersion: "3.13.0", AssetsPath: "/home/me/blenderkit_data"},
			expectedNew:            true,
			expectedSoftwaresCount: 1,
			expectedAppID:          2422,
			expectedName:           "Blender",
			expectedAssetsPath:     "/home/me/blenderkit_data",
		},
		{
			name:                   "Update connected Blender",
			inputSoftware:          Software{AppID: 2422, Name: "Blender", Version: "4.2.2", AddonVersion: "3.13.0", AssetsPath: "/home/me/another_path"},
			expectedNew:            false,
			expectedSoftwaresCount: 1,
			expectedAppID:          2422,
			expectedName:           "Blender",
			expectedAssetsPath:     "/home/me/another_path",
		},
		{
			name:                   "New Godot connected",
			inputSoftware:          Software{AppID: 7431, Name: "Godot", Version: "4.3.1", AddonVersion: "0.1.0", AssetsPath: "/home/me/godot/my_project"},
			expectedNew:            true,
			expectedSoftwaresCount: 2,
			expectedAppID:          7431,
			expectedName:           "Godot",
			expectedAssetsPath:     "/home/me/godot/my_project",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			beforeTime := time.Now()
			isNew := updateAvailableSoftware(tt.inputSoftware)
			afterTime := time.Now()
			if isNew != tt.expectedNew {
				t.Errorf("Expected new software: %v, got: %v", tt.expectedNew, isNew)
			}

			AvailableSoftwaresMux.Lock()
			defer AvailableSoftwaresMux.Unlock()

			if len(AvailableSoftwares) != tt.expectedSoftwaresCount {
				t.Errorf("Expected %d softwares, got %d", tt.expectedSoftwaresCount, len(AvailableSoftwares))
			}

			software, exists := AvailableSoftwares[tt.expectedAppID]
			if !exists {
				t.Errorf("Software with appID %d not found in AvailableSoftwares", tt.expectedAppID)
			}

			if software.Name != tt.expectedName {
				t.Errorf("Expected software name %s, got %s", tt.expectedName, software.Name)
			}

			if software.AssetsPath != tt.expectedAssetsPath {
				t.Errorf("Expected AssetsPath %s, got %s", tt.expectedAssetsPath, software.AssetsPath)
			}

			if !(beforeTime.Before(software.lastTimeConnected)) {
				t.Errorf("Time before (%v) calling update is not Before lastTimeConnected (%v)", beforeTime, software.lastTimeConnected)
			}

			if !(afterTime.After(software.lastTimeConnected)) {
				t.Errorf("Time after (%v) calling update is not After lastTimeConnected (%v)", afterTime, software.lastTimeConnected)
			}
		})
	}
	// clean global variables after the test
	AvailableSoftwares = make(map[int]Software)
	AvailableSoftwaresMux = sync.Mutex{}
}
func TestBkclientjsStatusHandler(t *testing.T) {
	tests := []struct {
		name                 string
		availableSoftwares   map[int]Software
		expectedStatus       int
		expectedClientStatus ClientStatus
	}{
		{
			name:               "Empty software list",
			availableSoftwares: map[int]Software{},
			expectedStatus:     http.StatusOK,
			expectedClientStatus: ClientStatus{
				ClientVersion: ClientVersion,
				Softwares:     nil,
			},
		},
		{
			name: "Single software",
			availableSoftwares: map[int]Software{
				1001: {AppID: 1001, Name: "Blender", Version: "4.2.1", AddonVersion: "3.13.0"},
			},
			expectedStatus: http.StatusOK,
			expectedClientStatus: ClientStatus{
				ClientVersion: ClientVersion,
				Softwares: []Software{
					{AppID: 1001, Name: "Blender", Version: "4.2.1", AddonVersion: "3.13.0"},
				},
			},
		},
		{
			name: "Multiple softwares",
			availableSoftwares: map[int]Software{
				1001: {AppID: 1001, Name: "Blender", Version: "4.2.1", AddonVersion: "3.13.0"},
				2222: {AppID: 2222, Name: "Godot", Version: "4.3.0", AddonVersion: "0.1.0"},
			},
			expectedStatus: http.StatusOK,
			expectedClientStatus: ClientStatus{
				ClientVersion: ClientVersion,
				Softwares: []Software{
					{AppID: 1001, Name: "Blender", Version: "4.2.1", AddonVersion: "3.13.0"},
					{AppID: 2222, Name: "Godot", Version: "4.3.0", AddonVersion: "0.1.0"},
				},
			},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			AvailableSoftwares = tt.availableSoftwares
			AvailableSoftwaresMux = sync.Mutex{}

			req, err := http.NewRequest("GET", "/status", nil)
			if err != nil {
				t.Fatal(err)
			}

			rr := httptest.NewRecorder()
			handler := http.HandlerFunc(bkclientjsStatusHandler)

			handler.ServeHTTP(rr, req)

			if status := rr.Code; status != tt.expectedStatus {
				t.Errorf("handler returned wrong status code: got %v want %v", status, tt.expectedStatus)
			}

			var clientStatus ClientStatus
			err = json.Unmarshal(rr.Body.Bytes(), &clientStatus)
			if err != nil {
				t.Fatalf("Could not unmarshal response body: %v", err)
			}

			sortSoftwares(clientStatus.Softwares)
			sortSoftwares(tt.expectedClientStatus.Softwares)
			if !reflect.DeepEqual(clientStatus, tt.expectedClientStatus) {
				t.Errorf("handler returned unexpected clientStatus: got %v want %v", clientStatus, tt.expectedClientStatus)
			}

			if rr.Header().Get("Access-Control-Allow-Origin") != "*" {
				t.Errorf("handler did not set correct Access-Control-Allow-Origin header")
			}

			if rr.Header().Get("Access-Control-Allow-Methods") != "GET, POST, OPTIONS" {
				t.Errorf("handler did not set correct Access-Control-Allow-Methods header")
			}

			if rr.Header().Get("Access-Control-Allow-Headers") != "Content-Type" {
				t.Errorf("handler did not set correct Access-Control-Allow-Headers header")
			}

			// clean global variables after the test
			AvailableSoftwares = make(map[int]Software)
			AvailableSoftwaresMux = sync.Mutex{}
		})
	}
}

// Helper function to sort the Software slice by AppID
// so we can run DeepEqual robustly.
func sortSoftwares(softwares []Software) {
	sort.Slice(softwares, func(i, j int) bool {
		return softwares[i].AppID < softwares[j].AppID
	})
}

func TestTaskFinish(t *testing.T) {
	tests := []struct {
		name           string
		initialStatus  string
		initialMessage string
		finishMessage  string
		expectedStatus string
	}{
		{
			name:           "Finish task with empty initial message",
			initialStatus:  "running",
			initialMessage: "",
			finishMessage:  "Task completed successfully",
			expectedStatus: "finished",
		},
		{
			name:           "Finish task with existing message",
			initialStatus:  "processing",
			initialMessage: "Processing data",
			finishMessage:  "Data processing complete",
			expectedStatus: "finished",
		},
		{
			name:           "Finish already finished task",
			initialStatus:  "finished",
			initialMessage: "Task already done",
			finishMessage:  "Attempting to finish again",
			expectedStatus: "finished",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			task := &Task{
				Status:  tt.initialStatus,
				Message: tt.initialMessage,
			}
			task.Finish(tt.finishMessage)

			if task.Status != tt.expectedStatus {
				t.Errorf("Expected status %s, got %s", tt.expectedStatus, task.Status)
			}
			if task.Message != tt.finishMessage {
				t.Errorf("Expected message %s, got %s", tt.finishMessage, task.Message)
			}
		})
	}
}

func TestNewTask(t *testing.T) {
	tests := []struct {
		name     string
		data     interface{}
		appID    int
		taskID   string
		taskType string
	}{
		{
			name:     "New task with nil data",
			data:     nil,
			appID:    1001,
			taskID:   "task1",
			taskType: "download",
		},
		{
			name:     "New task with map data",
			data:     map[string]interface{}{"key": "value"},
			appID:    2000,
			taskID:   "task2",
			taskType: "upload",
		},
		{
			name:     "New task with slice data",
			data:     []string{"item1", "item2"},
			appID:    3000,
			taskID:   "task3",
			taskType: "process",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			task := NewTask(tt.data, tt.appID, tt.taskID, tt.taskType)

			if task == nil {
				t.Fatal("NewTask returned nil")
			}

			if tt.data == nil {
				if _, ok := task.Data.(map[string]interface{}); !ok {
					t.Errorf("Expected Data to be map[string]interface{}, got %T", task.Data)
				}
			} else {
				if !reflect.DeepEqual(task.Data, tt.data) {
					t.Errorf("Expected Data %v, got %v", tt.data, task.Data)
				}
			}

			if task.AppID != tt.appID {
				t.Errorf("Expected AppID %d, got %d", tt.appID, task.AppID)
			}

			if task.TaskID != tt.taskID {
				t.Errorf("Expected TaskID %s, got %s", tt.taskID, task.TaskID)
			}

			if task.TaskType != tt.taskType {
				t.Errorf("Expected TaskType %s, got %s", tt.taskType, task.TaskType)
			}

			if task.Status != "created" {
				t.Errorf("Expected Status 'created', got %s", task.Status)
			}

			if task.Progress != 0 {
				t.Errorf("Expected Progress 0, got %d", task.Progress)
			}

			if task.Message != "" {
				t.Errorf("Expected empty Message, got %s", task.Message)
			}

			if task.MessageDetailed != "" {
				t.Errorf("Expected empty MessageDetailed, got %s", task.MessageDetailed)
			}

			if result, ok := task.Result.(map[string]interface{}); !ok {
				t.Errorf("Expected Result to be map[string]interface{}, got %T", task.Data)
			} else {
				if len(result) != 0 {
					t.Errorf("Expected Result to be empty map[string]interface{}, got %T of length %d", result, len(result))
				}
			}

			if task.Error != nil {
				t.Errorf("Expected nil Error, got %v", task.Error)
			}

			if task.Ctx == nil {
				t.Error("Expected non-nil Ctx")
			}

			if task.Cancel == nil {
				t.Error("Expected non-nil Cancel function")
			}
		})
	}
}
func TestGetAssetInstance(t *testing.T) {
	originalServer := Server
	tempServer := "http://test-server.com"
	Server = &tempServer
	defer func() { Server = originalServer }()

	tests := []struct {
		name        string
		assetBaseID string
		mockResp    *http.Response
		want        Asset
		wantErr     bool
		errContains string
	}{
		{
			name:        "Successful asset retrieval",
			assetBaseID: "abc123",
			mockResp: &http.Response{
				StatusCode: http.StatusOK,
				Body: io.NopCloser(bytes.NewBufferString(`{
					"results": [{
						"id": "abc123",
						"name": "Test Asset",
						"description": "Test Description"
					}]
				}`)),
			},
			want: Asset{
				ID:          "abc123",
				Name:        "Test Asset",
				Description: "Test Description",
			},
			wantErr: false,
		},
		{
			name:        "Empty results",
			assetBaseID: "nonexistent",
			mockResp: &http.Response{
				StatusCode: http.StatusOK,
				Body:       io.NopCloser(bytes.NewBufferString(`{"results": []}`)),
			},
			wantErr:     true,
			errContains: "0 assets found with asset_base_id=nonexistent",
		},
		{
			name:        "Multiple results",
			assetBaseID: "duplicate",
			mockResp: &http.Response{
				StatusCode: http.StatusOK,
				Body: io.NopCloser(bytes.NewBufferString(`{
					"results": [
						{"id": "1", "name": "Asset 1"},
						{"id": "2", "name": "Asset 2"}
					]
				}`)),
			},
			want: Asset{
				ID:   "1",
				Name: "Asset 1",
			},
			wantErr: false,
		},
		{
			name:        "Invalid JSON response",
			assetBaseID: "invalid",
			mockResp: &http.Response{
				StatusCode: http.StatusOK,
				Body:       io.NopCloser(bytes.NewBufferString(`invalid json`)),
			},
			wantErr: true,
		},
		{
			name:        "Server error",
			assetBaseID: "error",
			mockResp: &http.Response{
				StatusCode: http.StatusInternalServerError,
				Body:       io.NopCloser(bytes.NewBufferString(`{"detail": "Internal server error"}`)),
			},
			wantErr:     true,
			errContains: "error getting asset",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			originalClient := http.DefaultClient
			mockClient := &http.Client{
				Transport: &mockTransport{
					response: tt.mockResp,
				},
			}
			http.DefaultClient = mockClient
			defer func() { http.DefaultClient = originalClient }()

			got, err := GetAssetInstance(tt.assetBaseID)
			if (err != nil) != tt.wantErr {
				t.Errorf("GetAssetInstance() error = %v, wantErr %v", err, tt.wantErr)
				return
			}

			if tt.wantErr {
				if tt.errContains != "" && !strings.Contains(err.Error(), tt.errContains) {
					t.Errorf("GetAssetInstance() error = %v, want error containing %v", err, tt.errContains)
				}
				return
			}

			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("GetAssetInstance() = %v, want %v", got, tt.want)
			}
		})
	}
}

type mockTransport struct {
	response *http.Response
}

func (m *mockTransport) RoundTrip(req *http.Request) (*http.Response, error) {
	if m.response == nil {
		return nil, fmt.Errorf("no response configured")
	}
	m.response.Request = req
	return m.response, nil
}
