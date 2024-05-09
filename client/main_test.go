package main

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"net/url"
	"reflect"
	"strings"
	"testing"
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
