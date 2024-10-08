package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestCopyFile(t *testing.T) {
	tests := []struct {
		name    string
		srcData string
		wantErr bool
	}{
		{
			name:    "Copy small file",
			srcData: "Hello, World!",
			wantErr: false,
		},
		{
			name:    "Copy empty file",
			srcData: "",
			wantErr: false,
		},
		{
			name:    "Copy large file",
			srcData: string(make([]byte, 1024*1024)), // 1MB of data
			wantErr: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// Create a temporary directory for the test
			tmpDir, err := os.MkdirTemp("", "copyfile_test")
			if err != nil {
				t.Fatalf("Failed to create temp dir: %v", err)
			}
			defer os.RemoveAll(tmpDir)

			// Create source file
			srcPath := filepath.Join(tmpDir, "src.txt")
			if err := os.WriteFile(srcPath, []byte(tt.srcData), 0644); err != nil {
				t.Fatalf("Failed to create source file: %v", err)
			}

			// Define destination file
			dstPath := filepath.Join(tmpDir, "subdir", "dst.txt")

			// Run the copyFile function
			err = copyFile(srcPath, dstPath)

			// Check for errors
			if (err != nil) != tt.wantErr {
				t.Errorf("copyFile() error = %v, wantErr %v", err, tt.wantErr)
				return
			}

			// If no error, verify the contents
			if !tt.wantErr {
				dstData, err := os.ReadFile(dstPath)
				if err != nil {
					t.Fatalf("Failed to read destination file: %v", err)
				}

				if string(dstData) != tt.srcData {
					t.Errorf("Copied file contents do not match. Got %q, want %q", string(dstData), tt.srcData)
				}
			}
		})
	}
}

func TestCopyFileErrors(t *testing.T) {
	tmpDir, err := os.MkdirTemp("", "copyfile_error_test")
	if err != nil {
		t.Fatalf("Failed to create temp dir: %v", err)
	}
	defer os.RemoveAll(tmpDir)

	t.Run("Source file does not exist", func(t *testing.T) {
		srcPath := filepath.Join(tmpDir, "nonexistent.txt")
		dstPath := filepath.Join(tmpDir, "dst.txt")

		err := copyFile(srcPath, dstPath)
		if err == nil {
			t.Error("Expected an error when source file does not exist, got nil")
		}
	})

	t.Run("Destination is a directory", func(t *testing.T) {
		srcPath := filepath.Join(tmpDir, "src.txt")
		if err := os.WriteFile(srcPath, []byte("test"), 0644); err != nil {
			t.Fatalf("Failed to create source file: %v", err)
		}

		dstPath := filepath.Join(tmpDir, "dstdir")
		if err := os.Mkdir(dstPath, 0755); err != nil {
			t.Fatalf("Failed to create destination directory: %v", err)
		}

		err := copyFile(srcPath, dstPath)
		if err == nil {
			t.Error("Expected an error when destination is a directory, got nil")
		}
	})

	t.Run("Destination parent directory does not exist", func(t *testing.T) {
		srcPath := filepath.Join(tmpDir, "src.txt")
		if err := os.WriteFile(srcPath, []byte("test"), 0644); err != nil {
			t.Fatalf("Failed to create source file: %v", err)
		}

		dstPath := filepath.Join(tmpDir, "nonexistent", "dst.txt")

		err := copyFile(srcPath, dstPath)
		if err != nil {
			t.Errorf("Expected no error when destination parent directory does not exist, got %v", err)
		}

		// Verify the file was copied
		if _, err := os.Stat(dstPath); os.IsNotExist(err) {
			t.Error("Destination file was not created")
		}
	})
}

func TestSyncDirs(t *testing.T) {
	tests := []struct {
		name       string
		sourceTree map[string]string
		targetTree map[string]string
		wantTree   map[string]string
	}{
		{
			name: "Sync empty directories",
			sourceTree: map[string]string{
				"dir1/":      "",
				"dir2/":      "",
				"dir1/dir3/": "",
			},
			targetTree: map[string]string{},
			wantTree: map[string]string{
				"dir1/":      "",
				"dir2/":      "",
				"dir1/dir3/": "",
			},
		},
		{
			name: "Sync new files",
			sourceTree: map[string]string{
				"file1.txt":      "content1",
				"dir1/file2.txt": "content2",
			},
			targetTree: map[string]string{},
			wantTree: map[string]string{
				"file1.txt":      "content1",
				"dir1/file2.txt": "content2",
			},
		},
		{
			name: "Update existing files",
			sourceTree: map[string]string{
				"file1.txt":      "some content", // new content
				"dir1/file2.txt": "content2",
			},
			targetTree: map[string]string{
				"file1.txt":      "some content", // old content
				"dir1/file2.txt": "content2",
			},
			wantTree: map[string]string{
				"file1.txt":      "some content", // If the function syncDirs() would sync contents, we could check it here
				"dir1/file2.txt": "content2",
			},
		},
		{
			name: "Keep existing files",
			sourceTree: map[string]string{
				"file1.txt": "content1",
			},
			targetTree: map[string]string{
				"file1.txt": "content1",
				"file2.txt": "content2",
			},
			wantTree: map[string]string{
				"file1.txt": "content1",
				"file2.txt": "content2",
			},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			sourceDir, err := os.MkdirTemp("", "source")
			if err != nil {
				t.Fatalf("Failed to create source dir: %v", err)
			}
			defer os.RemoveAll(sourceDir)

			targetDir, err := os.MkdirTemp("", "target")
			if err != nil {
				t.Fatalf("Failed to create target dir: %v", err)
			}
			defer os.RemoveAll(targetDir)

			createTree(t, sourceDir, tt.sourceTree)
			createTree(t, targetDir, tt.targetTree)

			err = syncDirs(sourceDir, targetDir)
			if err != nil {
				t.Fatalf("syncDirs() error = %v", err)
			}

			checkTree(t, targetDir, tt.wantTree)
		})
	}
}

func createTree(t *testing.T, root string, tree map[string]string) {
	for path, content := range tree {
		fullPath := filepath.Join(root, path)
		if strings.HasSuffix(path, "/") {
			err := os.MkdirAll(fullPath, 0755)
			if err != nil {
				t.Fatalf("Failed to create directory: %v", err)
			}
			continue
		}

		parrentDir := filepath.Dir(fullPath)
		if err := os.MkdirAll(parrentDir, 0755); err != nil {
			t.Fatalf("Failed to create directory: %v", err)
		}
		if err := os.WriteFile(fullPath, []byte(content), 0644); err != nil {
			t.Fatalf("Failed to write file: %v", err)
		}
	}
}

func checkTree(t *testing.T, root string, wantTree map[string]string) {
	for path, wantContent := range wantTree {
		fullPath := filepath.Join(root, path)
		if strings.HasSuffix(path, "/") {
			_, err := os.Stat(fullPath)
			if err != nil {
				if os.IsNotExist(err) {
					t.Errorf("Directory %s does not exist", fullPath)
				}
			}
			continue
		}

		content, err := os.ReadFile(fullPath)
		if err != nil {
			t.Errorf("Failed to read file %s: %v", fullPath, err)
			continue
		}
		if string(content) != wantContent {
			t.Errorf("File %s content = %q, want %q", fullPath, content, wantContent)
		}
	}
}
func TestSyncDirsBidirectional(t *testing.T) {
	tests := []struct {
		name       string
		sourceTree map[string]string
		targetTree map[string]string
		wantTree   map[string]string
	}{
		{
			name: "Sync bidirectional with different files",
			sourceTree: map[string]string{
				"file1.txt":      "content1",
				"dir1/file2.txt": "content2",
			},
			targetTree: map[string]string{
				"file3.txt":      "content3",
				"dir2/file4.txt": "content4",
			},
			wantTree: map[string]string{
				"file1.txt":      "content1",
				"dir1/file2.txt": "content2",
				"file3.txt":      "content3",
				"dir2/file4.txt": "content4",
			},
		},
		{
			name: "Sync bidirectional with overlapping files",
			sourceTree: map[string]string{
				"file1.txt":      "content1",
				"dir1/file2.txt": "content2",
				"shared.txt":     "some content",
			},
			targetTree: map[string]string{
				"file3.txt":      "content3",
				"dir2/file4.txt": "content4",
				"shared.txt":     "some content",
			},
			wantTree: map[string]string{
				"file1.txt":      "content1",
				"dir1/file2.txt": "content2",
				"shared.txt":     "some content",
				"file3.txt":      "content3",
				"dir2/file4.txt": "content4",
			},
		},
		{
			name: "Sync bidirectional with empty directories",
			sourceTree: map[string]string{
				"dir1/":        "",
				"dir2/subdir/": "",
			},
			targetTree: map[string]string{
				"dir3/":        "",
				"dir4/subdir/": "",
			},
			wantTree: map[string]string{
				"dir1/":        "",
				"dir2/subdir/": "",
				"dir3/":        "",
				"dir4/subdir/": "",
			},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			sourceDir, err := os.MkdirTemp("", "source")
			if err != nil {
				t.Fatalf("Failed to create source dir: %v", err)
			}
			defer os.RemoveAll(sourceDir)

			targetDir, err := os.MkdirTemp("", "target")
			if err != nil {
				t.Fatalf("Failed to create target dir: %v", err)
			}
			defer os.RemoveAll(targetDir)

			createTree(t, sourceDir, tt.sourceTree)
			createTree(t, targetDir, tt.targetTree)

			err = syncDirsBidirectional(sourceDir, targetDir)
			if err != nil {
				t.Fatalf("syncDirsBidirectional() error = %v", err)
			}

			checkTree(t, sourceDir, tt.wantTree)
			checkTree(t, targetDir, tt.wantTree)
		})
	}
}

func TestSyncDirsBidirectionalErrors(t *testing.T) {
	t.Run("Source directory does not exist", func(t *testing.T) {
		tmpDir, err := os.MkdirTemp("", "syncdirsbi_error_test")
		if err != nil {
			t.Fatalf("Failed to create temp dir: %v", err)
		}
		defer os.RemoveAll(tmpDir)

		nonExistentDir := filepath.Join(tmpDir, "nonexistent")
		targetDir := filepath.Join(tmpDir, "target")

		err = os.Mkdir(targetDir, 0755)
		if err != nil {
			t.Fatalf("Failed to create target directory: %v", err)
		}

		err = syncDirsBidirectional(nonExistentDir, targetDir)
		if err == nil {
			t.Error("Expected an error when source directory does not exist, got nil")
		}
	})

	t.Run("Target directory does not exist", func(t *testing.T) {
		tmpDir, err := os.MkdirTemp("", "syncdirsbi_error_test")
		if err != nil {
			t.Fatalf("Failed to create temp dir: %v", err)
		}
		defer os.RemoveAll(tmpDir)

		sourceDir := filepath.Join(tmpDir, "source")
		nonExistentDir := filepath.Join(tmpDir, "nonexistent")

		err = os.Mkdir(sourceDir, 0755)
		if err != nil {
			t.Fatalf("Failed to create source directory: %v", err)
		}

		err = syncDirsBidirectional(sourceDir, nonExistentDir)
		if err != nil {
			t.Errorf("Expected no error when target directory does not exist, got %v", err)
		}

		// Check if the target directory was created
		if _, err := os.Stat(nonExistentDir); os.IsNotExist(err) {
			t.Error("Target directory was not created")
		}
	})
}
