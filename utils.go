package main

import (
	"encoding/json"
	"fmt"
	"net/http"
)

// parseRequestJSON parses the JSON from the request and returns the parsed JSON and the app_id
func parseRequestJSON(r *http.Request) (map[string]interface{}, int, error) {
	var rJSON map[string]interface{}
	if err := json.NewDecoder(r.Body).Decode(&rJSON); err != nil {
		return nil, -0, fmt.Errorf("error parsing JSON: %v", err)
	}

	appIDFloat, appIDExists := rJSON["app_id"].(float64)
	if !appIDExists {
		return nil, -1, fmt.Errorf("invalid or missing 'app_id' in JSON")
	}
	return rJSON, int(appIDFloat), nil
}

func getHeaders(apiKey, systemID string) http.Header {
	headers := http.Header{
		"Accept":           []string{"application/json"},
		"Platform-Version": []string{PlatformVersion},
		"System-Id":        []string{systemID},
		"Addon-Version":    []string{Version},
	}
	if apiKey != "" {
		headers.Set("Authorization", "Bearer "+apiKey)
	}

	return headers
}
