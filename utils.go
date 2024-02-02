package main

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
	"path"
)

// parseRequestJSON parses the JSON from the request and returns the parsed JSON and the app_id
func parseRequestJSON(r *http.Request) (map[string]interface{}, int, error) {
	var rJSON map[string]interface{}
	if err := json.NewDecoder(r.Body).Decode(&rJSON); err != nil {
		return nil, -1, fmt.Errorf("error parsing JSON: %v", err)
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

func GetAddonVersionFromJSON(rJSON map[string]interface{}) (*AddonVersion, error) {
	adVer := &AddonVersion{}
	verString, addonVersionExists := rJSON["addon_version"].(string)
	if !addonVersionExists {
		return nil, fmt.Errorf("missing 'addon_version' in JSON")
	}
	if verString != "" {
		_, err := fmt.Sscanf(verString, "%d.%d.%d", &adVer.Major, &adVer.Minor, &adVer.Patch)
		if err != nil {
			err = fmt.Errorf("error parsing 'addon_version' in JSON: %v", err)
			return nil, err
		}
	}
	return adVer, nil
}

func GetBlenderVersionFromJSON(rJSON map[string]interface{}) (*BlenderVersion, error) {
	blVer := &BlenderVersion{}
	verString, blenderVersionExists := rJSON["blender_version"].(string)
	if !blenderVersionExists {
		return nil, fmt.Errorf("missing 'blender_version' in JSON")
	}
	if verString != "" {
		_, err := fmt.Sscanf(verString, "%d.%d.%d", &blVer.Major, &blVer.Minor, &blVer.Patch)
		if err != nil {
			err = fmt.Errorf("error parsing 'blender_version' in JSON: %v", err)
			return nil, err
		}
	}
	return blVer, nil
}

type BlenderVersion struct {
	Major int
	Minor int
	Patch int
}

type AddonVersion struct {
	Major int
	Minor int
	Patch int
}

// Extract the filename from a URL, used for thumbnails.
func ExtractFilenameFromURL(urlStr string) (string, error) {
	if urlStr == "" {
		return "", fmt.Errorf("empty URL")
	}
	parsedURL, err := url.Parse(urlStr)
	if err != nil {
		return "", err
	}
	filename := path.Base(parsedURL.Path)
	escaped := url.QueryEscape(filename) // addon needs files to have %2C instead of ,
	return escaped, nil
}

type ThumbnailDownloadData struct {
	ImagePath     string `json:"image_path"`
	ImageURL      string `json:"image_url"`
	AssetBaseID   string `json:"assetBaseId"`
	ThumbnailType string `json:"thumbnail_type"`
	Index         int    `json:"index"`
}
