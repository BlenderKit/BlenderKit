package main

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"net/url"
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
