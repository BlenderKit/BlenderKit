package main

import (
	"fmt"
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
)

// GetHeaders returns a set of HTTP headers to be used in requests to the server.
// These are the default headers which should be set to all requests of client to the server.
func getHeaders(apiKey, systemID, addonVersion, platformVersion string) http.Header {
	headers := http.Header{}
	headers.Set("Content-Type", "application/json")
	headers.Set("Platform-Version", platformVersion)
	headers.Set("System-ID", systemID)
	headers.Set("Addon-Version", addonVersion)
	headers.Set("Client-Version", Version)
	if apiKey != "" {
		headers.Set("Authorization", "Bearer "+apiKey)
	}
	return headers
}

func StringToAddonVersion(s string) (*AddonVersion, error) {
	adVer := &AddonVersion{}
	if s == "" {
		return nil, fmt.Errorf("empty 'addon_version'")
	}

	_, err := fmt.Sscanf(s, "%d.%d.%d", &adVer.Major, &adVer.Minor, &adVer.Patch)
	if err != nil {
		err = fmt.Errorf("error parsing 'addon_version' in JSON: %v", err)
		return nil, err
	}

	return adVer, nil
}

func StringToBlenderVersion(s string) (*BlenderVersion, error) {
	blVer := &BlenderVersion{}
	if s == "" {
		return nil, fmt.Errorf("empty 'blender_version'")
	}

	_, err := fmt.Sscanf(s, "%d.%d.%d", &blVer.Major, &blVer.Minor, &blVer.Patch)
	if err != nil {
		err = fmt.Errorf("error parsing 'blender_version' in JSON: %v", err)
		return nil, err
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
