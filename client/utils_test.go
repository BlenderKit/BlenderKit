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
	"reflect"
	"regexp"
	"strings"
	"testing"
)

func TestGetSystemID(t *testing.T) {
	regex := regexp.MustCompile("^[0-9]{15}$")
	actual := getSystemID()
	if !regex.MatchString(*actual) {
		t.Errorf("getSystemID() = %v; want a string of 15 integers", *actual)
	}
}

func TestStringToAddonVersion(t *testing.T) {
	tests := []struct {
		input    string
		expected *AddonVersionStruct
		err      error
	}{
		{"0.0.0", &AddonVersionStruct{Major: 0, Minor: 0, Patch: 0}, nil},
		{"1.2.3", &AddonVersionStruct{Major: 1, Minor: 2, Patch: 3}, nil},
		{"3.12.11", &AddonVersionStruct{Major: 3, Minor: 12, Patch: 11}, nil},
		{"3.13.5.241206", &AddonVersionStruct{Major: 3, Minor: 13, Patch: 5}, nil},
		{"", nil, fmt.Errorf("add-on version is empty string")},
		{"4", nil, fmt.Errorf("error parsing add-on version: unexpected EOF")},
		{"4.2", nil, fmt.Errorf("error parsing add-on version: unexpected EOF")},
	}

	for _, test := range tests {
		actual, err := StringToAddonVersion(test.input)
		if err != nil {
			if test.err == nil || err.Error() != test.err.Error() {
				t.Errorf("StringToAddonVersion(%q) returned error '%v'; want '%v'", test.input, err, test.err)
			}
		} else if !reflect.DeepEqual(actual, test.expected) {
			t.Errorf("StringToAddonVersion(%q) = %v; want %v", test.input, actual, test.expected)
		}
	}
}

func TestStringToBlenderVersion(t *testing.T) {
	tests := []struct {
		input    string
		expected *BlenderVersionStruct
		err      error
	}{
		{"2.92.0", &BlenderVersionStruct{Major: 2, Minor: 92, Patch: 0}, nil},
		{"3.3.15", &BlenderVersionStruct{Major: 3, Minor: 3, Patch: 15}, nil},
		{"4.0.1", &BlenderVersionStruct{Major: 4, Minor: 0, Patch: 1}, nil},
		{"4.1.21", &BlenderVersionStruct{Major: 4, Minor: 1, Patch: 21}, nil},
		{"4.1.21.241206", &BlenderVersionStruct{Major: 4, Minor: 1, Patch: 21}, nil},
		{"", nil, fmt.Errorf("blender version is empty string")},
		{"4", nil, fmt.Errorf("error parsing blender version: unexpected EOF")},
		{"4.2", nil, fmt.Errorf("error parsing blender version: unexpected EOF")},
	}

	for _, test := range tests {
		actual, err := StringToBlenderVersion(test.input)
		if err != nil {
			if test.err == nil || err.Error() != test.err.Error() {
				t.Errorf("StringToBlenderVersion(%q) returned error '%v'; want '%v'", test.input, err, test.err)
			}
		} else if !reflect.DeepEqual(actual, test.expected) {
			t.Errorf("StringToBlenderVersion(%q) = %v; want %v", test.input, actual, test.expected)
		}
	}
}

func TestGetAssetDirectoryName(t *testing.T) {
	tests := []struct {
		asset_name string
		asset_id   string
		expected   string
	}{
		{"CAT", "953ae6c1-7fcd-4521-8924-a092b5022a0a", "cat_953ae6c1-7fcd-4521-8924-a092b5022a0a"},
		{"Soap Dispenser_2", "2cf7c1b7-ada9-421e-b5de-cf674b646893", "soap-dispenser-2_2cf7c1b7-ada9-421e-b5de-cf674b646893"},
		{"domain.com", "5a5ab3b0-818a-4229-b39d-bd4d83272ad5", "domain-com_5a5ab3b0-818a-4229-b39d-bd4d83272ad5"},
		{"Happy? Sad!", "c181edbd-de56-418b-ab7f-120c06ded48f", "happy-sad_c181edbd-de56-418b-ab7f-120c06ded48f"},
		{"Beautiful Car With Very Long Name", "47992e4f-1091-46d2-aed0-2dd52b573411", "beautiful-car-wi_47992e4f-1091-46d2-aed0-2dd52b573411"},
	}

	for _, test := range tests {
		actual := GetAssetDirectoryName(test.asset_name, test.asset_id)
		if actual != test.expected {
			t.Errorf("GetAssetDirectoryName(%q, %q) = %q; want %q", test.asset_name, test.asset_id, actual, test.expected)
		}
	}
}

func TestSlugify(t *testing.T) {
	tests := []struct {
		input    string
		expected string
	}{
		{"", ""},
		{"Jane Doe", "jane-doe"},
		{"John A. Doe", "john-a-doe"},
		{"Anezka92", "anezka92"},
		{"My--Username", "my-username"},
		{"My__Username, 123", "my-username-123"},
		{"My? Name! Is: Dada", "my-name-is-dada"},
		{"Lorem ipsum dolor sit amet, consectetur adipiscing <-50th char is space, ending hyphen will be remove, leading to 49chars. Consectetur ante hendrerit.", "lorem-ipsum-dolor-sit-amet-consectetur-adipiscing"},
	}

	for _, test := range tests {
		actual := Slugify(test.input)
		if actual != strings.ToLower(actual) {
			t.Errorf("Slugify(%q) = %q; did not return a lowercase string", test.input, actual)
		}

		if actual != test.expected {
			t.Errorf("Slugify(%q) = %q; want %q", test.input, actual, test.expected)
		}
	}
}

func TestExtractFilenameFromURL(t *testing.T) {
	tests := []struct {
		input    string
		expected string
		err      error
	}{
		{"https://example.com/file.txt", "file.txt", nil},
		{"https://example.com/path/to/file.jpg", "file.jpg", nil},
		{"https://example.com/path/to/file%2Cwith%2Ccomma.txt", "file%2Cwith%2Ccomma.txt", nil},
		{"https://public.blenderkit.com/thumbnails/assets/57ec74ff91b54b2ca5a540cda907cf7a/files/thumbnail_99e43644-30de-4361-9a7e-605eaf7d6795.jpg.256x256_q85_crop-%2C.jpg.webp?webp_generated=1701166007", "thumbnail_99e43644-30de-4361-9a7e-605eaf7d6795.jpg.256x256_q85_crop-%2C.jpg.webp", nil},
		{"https://public.blenderkit.com/thumbnails/assets/6144bbda83ca47ec8b9adb813c56f660/files/thumbnail_59686100-7ad0-4b38-b6fd-5158a6192a31.png.256x256_q85_crop-%2C.png.webp?webp_generated=1709019959", "thumbnail_59686100-7ad0-4b38-b6fd-5158a6192a31.png.256x256_q85_crop-%2C.png.webp", nil},
		{"https://public.blenderkit.com/public-assets/assets/76d2e7eaa0af42a8b33e1498c1da22f8/files/blend_0551adba-93bf-4f0e-aaeb-73927db46f88.blend", "blend_0551adba-93bf-4f0e-aaeb-73927db46f88.blend", nil},
		{"https://d255qm5a95hvrp.cloudfront.net/assets/0a00681c598c42259f67b69e6642f5dc/files/resolution_2K_02dacc88-532e-4b68-b8cb-4f1b8df1814b.blend?Expires=1709125449&Signature=LO-Gp1BfBe3maWncgvOep4ZNM9DJj0AdtMtjd9IN~OZQ5HPG1Cfy5408Bd0GskRTcgHuXjthLbhS3cWzksJrNrYA2L3zglK1ThSpdTtG4KwgGzlcyj7FXqmaKFul8Kpqu3weQaN1uazSzZSw5dN3Qxq0mb~7mPm6b8s7bJ6YeyUiWyL8qK8T-ff7hkzwb0tCIAyA3~9ZRImiwL0-OePg4I9Jl9LA32v2BuVJVkXp-kQkDb3VFRbhz9WCjFp0al7SqsFcpiIuJoFWp7UjTurqM85VX4jra9LQocA2svRk8fbrhTHkQRvMKJ3onqaA1Ou2Q71~-mL1aXxEfapDNk3euA__&Key-Pair-Id=KHZSXFBGJQRJ3", "resolution_2K_02dacc88-532e-4b68-b8cb-4f1b8df1814b.blend", nil},
		{"", "", fmt.Errorf("empty URL")},
	}

	for _, test := range tests {
		actual, err := ExtractFilenameFromURL(test.input)
		if err != nil {
			if test.err == nil || err.Error() != test.err.Error() {
				t.Errorf("ExtractFilenameFromURL(%q) returned error '%v'; want '%v'", test.input, err, test.err)
			}
		} else if actual != test.expected {
			t.Errorf("ExtractFilenameFromURL(%q) = %q; want %q", test.input, actual, test.expected)
		}
	}
}
func TestServerToLocalFilename(t *testing.T) {
	tests := []struct {
		filename  string
		assetName string
		expected  string
	}{
		{"resolution_2K_a5cbcda4-d00c-4494-bbbc-be205a9eb5ca.blend", "Cat on Books Statue 3D Scan", "cat-on-books-statue-3d-scan_2K_a5cbcda4-d00c-4494-bbbc-be205a9eb5ca.blend"},
		{"resolution_2K_0d0e0897-8649-4c8d-8b0c-296b15c3f7a8.blend", "Apple iPad With Keyboard", "apple-ipad-with-keyboard_2K_0d0e0897-8649-4c8d-8b0c-296b15c3f7a8.blend"},
		{"resolution_0_5K_0ee98e49-98be-4b38-8c5e-a0eb4d99766d.blend", "Ikea pendant light", "ikea-pendant-light_0_5K_0ee98e49-98be-4b38-8c5e-a0eb4d99766d.blend"},
		{"resolution_1K_e4248d23-fedb-4aa4-ac4d-b824bc5d0da2.blend", "Ikea pendant light", "ikea-pendant-light_1K_e4248d23-fedb-4aa4-ac4d-b824bc5d0da2.blend"},
		{"blend_934e424b-d890-4ba7-98c3-85b733cdc94a.blend", "Gray Carpet (Procedural)", "gray-carpet-procedural_934e424b-d890-4ba7-98c3-85b733cdc94a.blend"},
		{"blend_6ab98d58-8502-4087-a007-f3bd23f393a7.blend", "White minimal product mockups", "white-minimal-product-mockups_6ab98d58-8502-4087-a007-f3bd23f393a7.blend"},
		{"blend_1234567890.blend", "Some Very Very Extremely Long Asset Name Which Needs To Be Shortened In the Final Blend File Name Or It Will Cause Problems on Windows", "some-very-very-extremely-long-asset-name-which-nee_1234567890.blend"},
	}

	for _, test := range tests {
		actual := ServerToLocalFilename(test.filename, test.assetName)
		if actual != test.expected {
			t.Errorf("ServerToLocalFilename(%q, %q) = %q; want %q", test.filename, test.assetName, actual, test.expected)
		}
	}
}
