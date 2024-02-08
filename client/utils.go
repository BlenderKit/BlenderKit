package main

import (
	"encoding/json"
	"fmt"
	"io/fs"
	"net/http"
	"net/url"
	"os"
	"path"
	"regexp"
	"strings"
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
	headers := http.Header{}
	headers.Set("Content-Type", "application/json")
	headers.Set("Platform-Version", PlatformVersion)
	headers.Set("system-id", systemID)
	headers.Set("addon-version", Version)
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

// Check if the file exists on the hard drive.
// Returns error if the file exists but is not a file.
func FileExists(filePath string) (bool, fs.FileInfo, error) {
	info, err := os.Stat(filePath)
	if os.IsNotExist(err) {
		return false, info, nil
	}
	if info.IsDir() {
		return false, info, fmt.Errorf("file is a directory")
	}
	return true, info, nil
}

func DeleteFile(filePath string) error {
	err := os.Remove(filePath)
	if err != nil {
		return err
	}
	return nil
}

// Files on server are saved in format: "resolution_2K_d5368c9d-092e-4319-afe1-dd765de6da01.blend" for resolution files, or "blend_d5368c9d-092e-4319-afe1-dd765de6da01.blend" for original files,
// but locally we want to store them as "asset-name_2K_d5368c9d-092e-4319-afe1-dd765de6da01.blend".
// This is for better human readability.
func ServerToLocalFilename(filename, assetName string) string {
	filename = strings.Replace(filename, "blend_", "", -1)
	filename = strings.Replace(filename, "resolution_", "", -1)
	lfn := Slugify(assetName) + "_" + filename
	return lfn
}

func Slugify(slug string) string {
	slug = strings.ToLower(slug) // Normalize string: convert to lowercase
	characters := "<>:\"/\\|?*., ()#"
	for _, ch := range characters {
		slug = strings.ReplaceAll(slug, string(ch), "_")
	}

	// Remove non-alpha characters, and convert spaces to hyphens.
	reg := regexp.MustCompile(`[^a-z0-9]+`)
	slug = reg.ReplaceAllString(slug, "-")
	slug = strings.Trim(slug, "-")

	// Replace multiple hyphens with a single one
	reg = regexp.MustCompile(`[-]+`)
	slug = reg.ReplaceAllString(slug, "-")

	// Ensure the slug does not exceed 50 characters
	if len(slug) > 50 {
		slug = slug[:50]
	}

	return slug
}
