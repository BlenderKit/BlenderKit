/*##### BEGIN GPL LICENSE BLOCK #####

  This program is free software; you can redistribute it and/or
  modify it under the terms of the GNU General Public License
  as published by the Free Software Foundation; either version 2
  of the License, or (at your option) any later version.

  This program is distributed in the hope that it will be useful,
  but WITHOUT ANY WARRANTY; without even the implied warranty of
  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
  GNU General Public License for more details.

  You should have received a copy of the GNU General Public License
  along with this program; if not, write to the Free Software Foundation,
  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.

##### END GPL LICENSE BLOCK #####*/

package main

import (
	"fmt"
	"io"
	"io/fs"
	"log"
	"net/http"
	"net/url"
	"os"
	"os/user"
	"path"
	"path/filepath"
	"regexp"
	"strings"

	"github.com/google/uuid"
)

// GetHeaders returns a set of HTTP headers to be used in requests to the server.
// These are the default headers which should be set to all requests of client to the server.
func getHeaders(apiKey, systemID, addonVersion, platformVersion string) http.Header {
	headers := http.Header{}
	headers.Set("Content-Type", "application/json")
	headers.Set("Platform-Version", platformVersion)
	headers.Set("System-ID", systemID)
	headers.Set("Addon-Version", addonVersion)
	headers.Set("Client-Version", ClientVersion)
	if apiKey != "" {
		headers.Set("Authorization", "Bearer "+apiKey)
	}
	return headers
}

// GetSystemID returns the NodeID of the machine as string of 15 integers.
// It is the same format as platform.platform() produces in Python.
func getSystemID() *string {
	var nodeInt uint64
	for _, b := range uuid.NodeID() {
		nodeInt = (nodeInt << 8) | uint64(b)
	}
	nodeStr := fmt.Sprintf("%015d", nodeInt)
	return &nodeStr
}

func StringToAddonVersion(s string) (*AddonVersion, error) {
	adVer := &AddonVersion{}
	if s == "" {
		return nil, fmt.Errorf("add-on version is empty string")
	}

	_, err := fmt.Sscanf(s, "%d.%d.%d", &adVer.Major, &adVer.Minor, &adVer.Patch)
	if err != nil {
		return nil, fmt.Errorf("error parsing add-on version: %w", err)
	}

	return adVer, nil
}

func StringToBlenderVersion(s string) (*BlenderVersion, error) {
	blVer := &BlenderVersion{}
	if s == "" {
		return nil, fmt.Errorf("blender version is empty string")
	}

	_, err := fmt.Sscanf(s, "%d.%d.%d", &blVer.Major, &blVer.Minor, &blVer.Patch)
	if err != nil {
		return nil, fmt.Errorf("error parsing blender version: %w", err)
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
// Mirrors utils.py/extract_filename_from_url()
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

// Check if the file exists on the hard drive.
// Returns error if the file exists but is not a file.
func FileExists(filePath string) (bool, fs.FileInfo, error) {
	info, err := os.Stat(filePath)
	if err != nil {
		if os.IsNotExist(err) {
			return false, info, nil
		}
		return false, info, err
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

// DeleteFileAndParentIfEmpty deletes the specified file and its parent directory if empty.
func DeleteFileAndParentIfEmpty(filePath string) {
	err := os.Remove(filePath)
	if err != nil {
		log.Printf("Error removing file %v: %v", filePath, err)
		return
	}

	assetDir := filepath.Dir(filePath)
	dirContents, err := os.ReadDir(assetDir)
	if err != nil {
		log.Printf("Error reading directory %v: %v", assetDir, err)
		return
	}

	if len(dirContents) == 0 {
		err := os.Remove(assetDir)
		if err != nil {
			log.Printf("Error removing directory %v: %v", assetDir, err)
		}
	}
}

// Convert server format filename to human readable local filename. Function mirrors: paths.py/serverToLocalFilename()
//
// "resolution_2K_d5368c9d-092e-4319-afe1-dd765de6da01.blend" > "asset-name_2K_d5368c9d-092e-4319-afe1-dd765de6da01.blend"
//
// "blend_d5368c9d-092e-4319-afe1-dd765de6da01.blend" > "asset-name_d5368c9d-092e-4319-afe1-dd765de6da01.blend"
func ServerToLocalFilename(serverFilename, assetName string) string {
	serverFilename = strings.Replace(serverFilename, "blend_", "", -1)
	serverFilename = strings.Replace(serverFilename, "resolution_", "", -1)
	localFilename := Slugify(assetName) + "_" + serverFilename

	return localFilename
}

// GetAssetDirectoryName returns the name of the directory in which resolution files will be stored.
// Function mirrors: paths.py/get_asset_directory_name()
func GetAssetDirectoryName(assetName, assetID string) string {
	slugifiedName := Slugify(assetName)
	if len(slugifiedName) > 16 {
		slugifiedName = slugifiedName[:16]
	}

	return fmt.Sprintf("%s_%s", slugifiedName, assetID)
}

// Slugify converts a string to a URL-friendly slug.
// Converts to lowercase, replaces non-alphanumeric characters with hyphens.
// Ensures only one hyphen between words and that string starts and ends with a letter or number.
// It also ensures that the slug does not exceed 50 characters.
func Slugify(slug string) string {
	// Normalize string: convert to lowercase
	slug = strings.ToLower(slug)

	// Remove non-alpha characters, and convert spaces to hyphens.
	reg := regexp.MustCompile(`[^a-z0-9]+`)
	slug = reg.ReplaceAllString(slug, "-")

	// Replace multiple hyphens with a single one
	reg = regexp.MustCompile(`[-]+`)
	slug = reg.ReplaceAllString(slug, "-")

	// Ensure the slug does not exceed 50 characters
	if len(slug) > 50 {
		slug = slug[:50]
	}

	// Ensure the slug starts and ends with a letter or number.
	slug = strings.Trim(slug, "-")

	return slug
}

// Helper function to calculate absolute value.
func abs(x int) int {
	if x < 0 {
		return -x
	}
	return x
}

// Iterate over each top-level category and updates its AssetCount
// to include the total count of assets from all its descendant categories.
// This is done by calling count_to_parent, which recursively processes each category and its children.
func fix_category_counts(categories []Category) {
	for i := range categories {
		count_to_parent(&categories[i])
	}
}

// Recursively update a category's AssetCount to include counts from all its children.
// It traverses the entire hierarchy of child categories, ensuring that the cumulative asset counts
// are correctly aggregated up to the top-level parent category.
func count_to_parent(parent *Category) {
	for i := range parent.Children {
		count_to_parent(&parent.Children[i])
		parent.AssetCount += parent.Children[i].AssetCount
	}
}

// GetSafeTempPath returns a safe, user-specific path in the system's temporary directory.
// This is the location where thumbnails, gravatars and other temporary files are stored.
//
// Contains dirs: bkit_g, brush_search, hdr_search, material_search, model_search, scene_search
//
// Contains files: categories.json.
func GetSafeTempPath() (string, error) {
	currentUser, err := user.Current()
	if err != nil {
		return "", err
	}

	username := currentUser.Username
	reg, err := regexp.Compile("[^a-zA-Z0-9]+")
	if err != nil {
		return "", err
	}
	safeUsername := reg.ReplaceAllString(username, "")

	tempDir := os.TempDir()
	safeTempPath := filepath.Join(tempDir, "bktemp_"+safeUsername)

	err = os.MkdirAll(safeTempPath, 0700)
	if err != nil {
		return "", err
	}

	return safeTempPath, nil
}

// FixAssetsUpdateResponse updates the response to contain the asset ID and AssetType.
// It has to be done because API returns different data response when asset is created and when it is updated.
// API assets_update returns different set of data, asset_type are missing.
// https://www.blenderkit.com/api/v1/docs/#tag/assets/operation/assets_create - provides ID and AssetType
// https://www.blenderkit.com/api/v1/docs/#tag/assets/operation/assets_update - does not provide ID and AssetType
func FixAssetsUpdateResponse(data *AssetsCreateResponse, assetID, assetType string) *AssetsCreateResponse {
	if data.ID == "" {
		fmt.Printf("FixAssetsUpdateResponse: assetID is empty, replacing with assetID: %v\n", assetID)
		data.ID = assetID
	} else {
		fmt.Println("FixAssetsUpdateResponse: assetID is not empty")
	}

	if data.AssetType == "" {
		fmt.Printf("FixAssetsUpdateResponse: assetType is empty, replacing with assetType: %v\n", assetType)
		data.AssetType = assetType
	} else {
		fmt.Println("FixAssetsUpdateResponse: assetType is not empty")
	}

	return data
}

// Check if the HTTP response is of content type application/json.
// Return nil error if response is JSON.
// If response is not JSON, try to extract the error message and return readable error.
func RespIsJSON(resp *http.Response) error {
	contentType := resp.Header.Get("Content-Type")
	if strings.Contains(contentType, "application/json") {
		return nil
	}
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return fmt.Errorf("expected application/json, got %s and cannot read response body: %w", contentType, err)
	}
	bodyString := string(body)
	if strings.Contains(bodyString, "error code: 1015") {
		return fmt.Errorf("API rate limit exceeded, wait for a while (%s)", bodyString)
	}

	return fmt.Errorf("invalid response Content-Type: %s, resp: %s", contentType, bodyString)
}
