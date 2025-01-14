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

import "context"

// MinimalTaskData is minimal data needed from Blender add-on to schedule a task.
// This is used only for communication with Blender add-on. Other add-on will not schedule a tasks.
// From this also Software
type MinimalTaskData struct {
	AppID           int    `json:"app_id"`           // AppID is PID of Blender in which add-on runs
	APIKey          string `json:"api_key"`          // Can be empty for non-logged users
	AddonVersion    string `json:"addon_version"`    // X.Y.Z version of add-on
	BlenderVersion  string `json:"blender_version"`  // X.Y.X version of the Blender
	PlatformVersion string `json:"platform_version"` // Result of platform.platform() in Python
}

// Data required as part of the request for reports. There is extra field project_name expected, so
// the running add-on (Blender, Godot) can be identified more easily if multiple windows are opened.
type GetReportData struct {
	MinimalTaskData
	ProjectName           string `json:"project_name,omitempty"`  // Name of the currently opened project
	ExpectedClientVersion string `json:"expected_client_version"` // Version of the Client which the add-on expects
}

// TaskStatusUpdate is a struct for updating the status of a task through a channel.
// Message is optional and should be set to "" if update is not needed.
type TaskProgressUpdate struct {
	AppID           int
	TaskID          string
	Progress        int
	Message         string
	MessageDetailed string
}

// TaskMessageUpdate is a struct for updating the message of a task through a channel.
type TaskMessageUpdate struct {
	AppID           int
	TaskID          string
	Message         string
	MessageDetailed string
}

// TaskError is a struct for reporting an error in a task through a channel.
// Error will be converted to string and stored in the task's Message field.
type TaskError struct {
	AppID           int
	TaskID          string
	Error           error
	Result          interface{}
	MessageDetailed string
}

// TaskProgressUpdate is a struct for updating the progress of a task through a channel.
type TaskFinish struct {
	AppID           int
	TaskID          string
	Message         string
	MessageDetailed string
	Result          interface{}
}

type TaskCancel struct {
	AppID  int
	TaskID string
	Reason string
}

// Task is a struct for storing a task in this Client application.
// Exported fields are used for JSON encoding/decoding and are defined in same in the add-on.
type Task struct {
	Data            interface{}        `json:"data"`             // Data for the task, should be a struct like DownloadData, SearchData, etc.
	AppID           int                `json:"app_id"`           // PID of the Blender running the add-on
	TaskID          string             `json:"task_id"`          // random UUID for the task
	TaskType        string             `json:"task_type"`        // search, download, etc.
	Message         string             `json:"message"`          // Short message for the user
	MessageDetailed string             `json:"message_detailed"` // Longer message to the console
	Progress        int                `json:"progress"`         // 0-100
	Status          string             `json:"status"`           // created, finished, error
	Result          interface{}        `json:"result"`           // Result to be used by the add-on
	Error           error              `json:"-"`                // Internal: error in the task, not to be sent to the add-on
	Ctx             context.Context    `json:"-"`                // Internal: Context for canceling the task, use in long running functions which support it
	Cancel          context.CancelFunc `json:"-"`                // Internal: Function for canceling the task
}

// SocialNetworkDetails stores details about a social network.
// For some reason it is not implemented in the Social Network directly by the API, but as sub-struct.
type SocialNetworkDetails struct {
	Icon  string `json:"icon"`
	Name  string `json:"name"`
	Order int    `json:"order"`
}

// SocialNetwork represents a social network filled in by author on their profile.
type SocialNetwork struct {
	URL                  string               `json:"url"`
	SocialNetworkDetails SocialNetworkDetails `json:"socialNetwork"`
}

// Author represents an author of an Asset.
type Author struct {
	AboutMe        string          `json:"aboutMe"`
	AboutMeURL     string          `json:"aboutMeUrl"` // URL to the author's portfolio on BlenderKit
	Avatar128      string          `json:"avatar128"`
	FirstName      string          `json:"firstName"`
	FullName       string          `json:"fullName"`
	GravatarHash   string          `json:"gravatarHash"`
	ID             int             `json:"id"`
	LastName       string          `json:"lastName"`
	SocialNetworks []SocialNetwork `json:"socialNetworks"`
}

// Asset is a struct for storing an asset in this Client application.
// Represents a single asset returned from the search API at: https://www.blenderkit.com/api/v1/search/.
type Asset struct {
	AddonVersion                     string                 `json:"addonVersion"`
	AssetBaseID                      string                 `json:"assetBaseId"`
	AssetType                        string                 `json:"assetType"`
	Author                           Author                 `json:"author"`
	CanDownload                      bool                   `json:"canDownload"`
	CanDownloadError                 interface{}            `json:"canDownloadError"` // False or {"messages": ["User is anonymous"], "type": "anonymous_user"} Oh yeah, tell me how is this logical!
	Category                         string                 `json:"category"`
	Created                          string                 `json:"created"`
	Description                      string                 `json:"description"`
	DictParameters                   map[string]interface{} `json:"dictParameters"`
	DisplayName                      string                 `json:"displayName"`
	Files                            []AssetFile            `json:"files"`
	FilesSize                        float64                `json:"filesSize"`
	ID                               string                 `json:"id"`
	IsFree                           bool                   `json:"isFree"`
	IsPrivate                        bool                   `json:"isPrivate"`
	LastBlendUpload                  string                 `json:"lastBlendUpload"`
	LastGltfUpload                   string                 `json:"lastGltfUpload"`
	LastResolutionUpload             string                 `json:"lastResolutionUpload"`
	LastThumbnailUpload              string                 `json:"lastThumbnailUpload"`
	LastUserInteraction              string                 `json:"lastUserInteraction"`
	LastVideoUpload                  string                 `json:"lastVideoUpload"`
	LastZipFileUpload                string                 `json:"lastZipFileUpload"`
	License                          string                 `json:"license"`
	Name                             string                 `json:"name"`
	PK                               int                    `json:"pk"`
	RatingsAverage                   map[string]interface{} `json:"ratingsAverage"`
	RatingsCount                     map[string]interface{} `json:"ratingsCount"`
	RatingsMedian                    map[string]interface{} `json:"ratingsMedian"`
	RatingsSum                       map[string]interface{} `json:"ratingsSum"`
	Score                            float64                `json:"score"`
	ShowMarketingLabels              bool                   `json:"showMarketingLabels"`
	SourceAppName                    string                 `json:"sourceAppName"`
	SourceAppVersion                 string                 `json:"sourceAppVersion"`
	Tags                             []string               `json:"tags"`
	ThumbnailLargeURL                string                 `json:"thumbnailLargeUrl"`
	ThumbnailLargeURLNonsquared      string                 `json:"thumbnailLargeUrlNonsquared"`
	ThumbnailLargeURLNonsquaredWebp  string                 `json:"thumbnailLargeUrlNonsquaredWebp"`
	ThumbnailLargeURLWebp            string                 `json:"thumbnailLargeUrlWebp"`
	ThumbnailMiddleURL               string                 `json:"thumbnailMiddleUrl"`
	ThumbnailMiddleURLNonsquared     string                 `json:"thumbnailMiddleUrlNonsquared"`
	ThumbnailMiddleURLNonsquaredWebp string                 `json:"thumbnailMiddleUrlNonsquaredWebp"`
	ThumbnailMiddleURLWebp           string                 `json:"thumbnailMiddleUrlWebp"`
	ThumbnailSmallURL                string                 `json:"thumbnailSmallUrl"`
	ThumbnailSmallURLNonsquared      string                 `json:"thumbnailSmallUrlNonsquared"`
	ThumbnailSmallURLNonsquaredWebp  string                 `json:"thumbnailSmallUrlNonsquaredWebp"`
	ThumbnailSmallURLWebp            string                 `json:"thumbnailSmallUrlWebp"`
	ThumbnailXlargeURL               string                 `json:"thumbnailXlargeUrl"`
	ThumbnailXlargeURLNonsquared     string                 `json:"thumbnailXlargeUrlNonsquared"`
	ThumbnailXlargeURLNonsquaredWebp string                 `json:"thumbnailXlargeUrlNonsquaredWebp"`
	ThumbnailXlargeURLWebp           string                 `json:"thumbnailXlargeUrlWebp"`
	URL                              string                 `json:"url"`
	VerificationStatus               string                 `json:"verificationStatus"`
	VersionNumber                    int                    `json:"versionNumber"`
	WebpGeneratedTimestamp           float64                `json:"webpGeneratedTimestamp"`
}

// SearchResults is a struct for storing search results from https://www.blenderkit.com/api/v1/search/.
type SearchResults struct {
	Count       int         `json:"count"`
	Facets      interface{} `json:"facets"`
	NextURL     string      `json:"next,omitempty"`
	PreviousURL string      `json:"previous,omitempty"`
	Results     []Asset     `json:"results"`
}

type PREFS struct {
	APIKey        string `json:"api_key"`
	APIKeyRefres  string `json:"api_key_refresh"`
	APIKeyTimeout int    `json:"api_key_timeout"`
	SceneID       string `json:"scene_id"`
	AppID         int    `json:"app_id"`
	UnpackFiles   bool   `json:"unpack_files"`
	Resolution    string `json:"resolution"` // "ORIGINAL", "resolution_0_5K", "resolution_1K", "resolution_2K", "resolution_4K", "resolution_8K"
	// PATHS
	ProjectSubdir   string `json:"project_subdir"`
	GlobalDir       string `json:"global_dir"`
	BinaryPath      string `json:"binary_path"`
	AddonDir        string `json:"addon_dir"`
	AddonModuleName string `json:"addon_module_name"` // __package__ of the add-on, for legacy addons was "blenderkit", extensions "bl_ext.user_default.blenderkit" or anything else!
}

// AssetFile represents a file in an asset.
// Used in Download (downloading .blend file) and Search (downloading thumbnails).
type AssetFile struct {
	Created            string `json:"created"`
	DownloadURL        string `json:"downloadUrl"` // URL from which the real download URL can be retrieved
	FileThumbnail      string `json:"fileThumbnail"`
	FileThumbnailLarge string `json:"fileThumbnailLarge"`
	FileType           string `json:"fileType"`
	Modified           string `json:"modified"`
	Resolution         int    `json:"resolution"` // null for asset (resolution) files, thumbnails, but is integer for videos

	URL      string `json:"url"`      // retrieved URL to the actual file
	Filename string `json:"filename"` // filename of the file to be saved.
}

type DownloadAssetData struct {
	Name                 string      `json:"name"`
	ID                   string      `json:"id"`
	AvailableResolutions []int       `json:"available_resolutions"`
	Files                []AssetFile `json:"files"`
	AssetType            string      `json:"assetType"`  // needed for unpacking
	Resolution           string      `json:"resolution"` // needed for unpacking
}

type DownloadData struct {
	AddonVersion      string            `json:"addon_version"`
	PlatformVersion   string            `json:"platform_version"`
	AppID             int               `json:"app_id"`
	DownloadDirs      []string          `json:"download_dirs"`
	Resolution        string            `json:"resolution"` // used to populate DownloadAssetData.Resolution
	DownloadAssetData DownloadAssetData `json:"asset_data"`
	Preferences       PREFS             `json:"PREFS"`
}

type Category struct {
	Name                 string     `json:"name"`
	Slug                 string     `json:"slug"`
	Active               bool       `json:"active"`
	Thumbnail            string     `json:"thumbnail"`
	ThumbnailWidth       int        `json:"thumbnailWidth"`
	ThumbnailHeight      int        `json:"thumbnailHeight"`
	Order                int        `json:"order"`
	AlternateTitle       string     `json:"alternateTitle"`
	AlternateURL         string     `json:"alternateUrl"`
	Description          string     `json:"description"`
	MetaKeywords         string     `json:"metaKeywords"`
	MetaExtra            string     `json:"metaExtra"`
	Children             []Category `json:"children"`
	AssetCount           int        `json:"assetCount"`
	AssetCountCumulative int        `json:"assetCountCumulative"`
}

// CategoriesData is a struct for storing the response from the server when fetching https://www.blenderkit.com/api/v1/categories/
type CategoriesData struct {
	Count   int        `json:"count"`
	Next    string     `json:"next"`
	Prev    string     `json:"previous"`
	Results []Category `json:"results"`
}

type S3UploadInfoResponse struct {
	AssetID          string `json:"assetId"`
	FilePath         string `json:"filePath"`
	FileType         string `json:"fileType"`
	ID               string `json:"id"`
	OriginalFilename string `json:"originalFilename"`
	S3UploadURL      string `json:"s3UploadUrl"`
	UploadDoneURL    string `json:"uploadDoneUrl"`
	UploadURL        string `json:"uploadUrl"`
}

type PackingData struct {
	ExportData AssetUploadExportData `json:"export_data"`
	UploadData AssetsCreateResponse  `json:"upload_data"`
	UploadSet  []string              `json:"upload_set"`
}

type UploadFile struct {
	Type     string
	Index    int
	FilePath string
}

type AssetParameterData struct {
	Parametertype string `json:"parameterType"`
	Value         string `json:"value"`
}

type AssetUploadExportData struct {
	Models    []string `json:"models,omitempty"`    // Only for models upload
	Material  string   `json:"material,omitempty"`  // Only for material upload
	Scene     string   `json:"scene,omitempty"`     // Only for scene upload
	Brush     string   `json:"brush,omitempty"`     // Only for brush upload
	NodeGroup string   `json:"nodegroup,omitempty"` // Only for node group upload
	// Common parameters
	ThumbnailPath     string `json:"thumbnail_path"`
	AssetBaseID       string `json:"assetBaseId"`
	ID                string `json:"id"`
	EvalPathComputing string `json:"eval_path_computing"`
	EvalPathState     string `json:"eval_path_state"`
	EvalPath          string `json:"eval_path"`
	TempDir           string `json:"temp_dir"`
	SourceFilePath    string `json:"source_filepath"`
	BinaryPath        string `json:"binary_path"`
	DebugValue        int    `json:"debug_value"`
	HDRFilepath       string `json:"hdr_filepath,omitempty"`
}

// Data response on assets_create or assets_update. Quite close to AssetUploadTaskData. TODO: merge together.
// API docs:
// https://www.blenderkit.com/api/v1/docs/#tag/assets/operation/assets_create
// https://www.blenderkit.com/api/v1/docs/#tag/assets/operation/assets_update
type AssetsCreateResponse struct {
	AddonVersion       string      `json:"addonVersion"`
	AssetBaseID        string      `json:"assetBaseId"`
	AssetType          string      `json:"assetType"`
	Category           string      `json:"category"`
	Description        string      `json:"description"`
	DisplayName        string      `json:"displayName"`
	ID                 string      `json:"id"`
	IsFree             bool        `json:"isFree"`
	IsPrivate          bool        `json:"isPrivate"`
	License            string      `json:"license"`
	Name               string      `json:"name"`
	Parameters         interface{} `json:"parameters"`
	SourceAppName      string      `json:"sourceAppName"`
	SourceAppVersion   string      `json:"sourceAppVersion"`
	Tags               []string    `json:"tags"`
	URL                string      `json:"url"`
	VerificationStatus string      `json:"verificationStatus"`
	VersionNumber      string      `json:"versionNumber"`
}

// AssetUploadTaskData is expected from the add-on. Used to create/update metadata on asset.
// API docs:
// https://www.blenderkit.com/api/v1/docs/#tag/assets/operation/assets_create
// https://www.blenderkit.com/api/v1/docs/#tag/assets/operation/assets_update
type AssetUploadData struct {
	AddonVersion     string      `json:"addonVersion"`
	PlatformVersion  string      `json:"platformVersion"`
	AssetType        string      `json:"assetType"`
	Category         string      `json:"category"`
	Description      string      `json:"description"`
	DisplayName      string      `json:"displayName"`
	IsFree           bool        `json:"isFree"`
	IsPrivate        bool        `json:"isPrivate"`
	License          string      `json:"license"`
	Name             string      `json:"name,omitempty"` // has to be ommited for metadata reupload
	Parameters       interface{} `json:"parameters"`
	SourceAppName    string      `json:"sourceAppName"`
	SourceAppVersion string      `json:"sourceAppVersion"`
	Tags             []string    `json:"tags"`

	// Not required
	VerificationStatus string `json:"verificationStatus,omitempty"`
	AssetBaseID        string `json:"assetBaseId,omitempty"`
	ID                 string `json:"id,omitempty"`
}

// AssetUploadTaskData is expected from the add-on.
type AssetUploadRequestData struct {
	AppID       int                   `json:"app_id"`
	Preferences PREFS                 `json:"PREFS"`
	UploadData  AssetUploadData       `json:"upload_data"`
	ExportData  AssetUploadExportData `json:"export_data"`
	UploadSet   []string              `json:"upload_set"`
}

// MarkNotificationReadTaskData is expected from the add-on.
type MarkNotificationReadTaskData struct {
	AddonVersion    string `json:"addon_version"`
	PlatformVersion string `json:"platform_version"`
	AppID           int    `json:"app_id"`
	APIKey          string `json:"api_key"`
	Notification    int    `json:"notification_id"`
}

// MarkCommentPrivateTaskData is expected from the add-on.
type MarkCommentPrivateTaskData struct {
	AddonVersion    string `json:"addon_version"`
	PlatformVersion string `json:"platform_version"`
	AppID           int    `json:"app_id"`
	APIKey          string `json:"api_key"`
	AssetID         string `json:"asset_id"`
	CommentID       int    `json:"comment_id"`
	IsPrivate       bool   `json:"is_private"`
}

// MarkCommentPrivateData is sent to the server.
type MarkCommentPrivateData struct {
	IsPrivate bool `json:"is_private"`
}

// FeedbackCommentTaskData is expected from the add-on.
type FeedbackCommentTaskData struct {
	AddonVersion    string `json:"addon_version"`
	PlatformVersion string `json:"platform_version"`
	AppID           int    `json:"app_id"`
	APIKey          string `json:"api_key"`
	AssetID         string `json:"asset_id"`
	CommentID       int    `json:"comment_id"`
	Flag            string `json:"flag"`
}

// FeedbackCommentData is sent to the server.
type FeedbackCommentData struct {
	CommentID int    `json:"comment"`
	Flag      string `json:"flag"`
}

type GetCommentsResponseForm struct {
	Timestamp    string `json:"timestamp"`
	SecurityHash string `json:"securityHash"`
}

type GetCommentsResponse struct {
	Form GetCommentsResponseForm `json:"form"`
}

type CommentPostData struct {
	Name         string `json:"name"`
	Email        string `json:"email"`
	URL          string `json:"url"`
	Followup     bool   `json:"followup"`
	ReplyTo      int    `json:"reply_to"`
	Honeypot     string `json:"honeypot"`
	ContentType  string `json:"content_type"`
	ObjectPK     string `json:"object_pk"`
	Timestamp    string `json:"timestamp"`
	SecurityHash string `json:"security_hash"`
	Comment      string `json:"comment"`
}

type CreateCommentData struct {
	AddonVersion    string `json:"addon_version"`
	PlatformVersion string `json:"platform_version"`
	AppID           int    `json:"app_id"`
	APIKey          string `json:"api_key"`
	AssetID         string `json:"asset_id"`
	CommentText     string `json:"comment_text"`
	ReplyToID       int    `json:"reply_to_id"`
}

type GetCommentsData struct {
	AddonVersion    string `json:"addon_version"`
	PlatformVersion string `json:"platform_version"`
	AppID           int    `json:"app_id"`
	APIKey          string `json:"api_key"`
	AssetID         string `json:"asset_id"`
}

type FetchGravatarData struct {
	AddonVersion    string `json:"addon_version"`
	PlatformVersion string `json:"platform_version"`
	AppID           int    `json:"app_id"`
	ID              int    `json:"id"`
	Avatar128       string `json:"avatar128"` //e.g.: "/avatar-redirect/ad7c20a8-98ca-4128-9189-f727b2d1e4f3/128/"
	GravatarHash    string `json:"gravatarHash"`
}

type CancelDownloadData struct {
	TaskID string `json:"task_id"`
	AppID  int    `json:"app_id"`
}

// MARK: RATINGS

type GetRatingData struct {
	AddonVersion    string `json:"addon_version"`
	PlatformVersion string `json:"platform_version"`
	AppID           int    `json:"app_id"`
	APIKey          string `json:"api_key"`
	AssetID         string `json:"asset_id"`
}

type GetRatingsResponse struct {
	Count    int      `json:"count"`
	Next     string   `json:"next"`
	Previous string   `json:"previous"`
	Results  []Rating `json:"results"`
}

// Rating data obtained from the server.
type Rating struct {
	Score      float32     `json:"score"`
	RatingType string      `json:"ratingType"`
	Asset      RatingAsset `json:"asset"`
}

type RatingAsset struct {
	AssetUUID   string `json:"assetUuid"`   // aka assetBaseID
	VersionUUID string `json:"versionUuid"` // aka ID
}

type SendRatingData struct {
	AddonVersion    string  `json:"addon_version"`
	PlatformVersion string  `json:"platform_version"`
	AppID           int     `json:"app_id"`
	APIKey          string  `json:"api_key"`
	AssetID         string  `json:"asset_id"`
	RatingType      string  `json:"rating_type"`
	RatingValue     float32 `json:"rating_value"`
}

type Notification struct {
	ID          int                       `json:"id"`
	Recipient   NotificationRecipient     `json:"recipient"`
	Actor       NotificationActor         `json:"actor"`
	Target      NotificationTarget        `json:"target"`
	Verb        string                    `json:"verb"`
	ActionObj   *NotificationActionObject `json:"actionObject"`
	Level       string                    `json:"level"`
	Description string                    `json:"description"`
	Unread      bool                      `json:"unread"`
	Public      bool                      `json:"public"`
	Deleted     bool                      `json:"deleted"`
	Emailed     bool                      `json:"emailed"`
	Timestamp   string                    `json:"timestamp"`
	String      string                    `json:"string"`
}

type NotificationActor struct {
	PK               interface{} `json:"pk"` // for some reason it can be int or string
	ContentTypeName  string      `json:"contentTypeName"`
	ContentTypeModel string      `json:"contentTypeModel"`
	ContentTypeApp   string      `json:"contentTypeApp"`
	ContentTypeID    int         `json:"contentTypeId"`
	URL              string      `json:"url"`
	String           string      `json:"string"`
}

type NotificationTarget struct {
	PK               interface{} `json:"pk"` // for some reason it can be int or string
	ContentTypeName  string      `json:"contentTypeName"`
	ContentTypeModel string      `json:"contentTypeModel"`
	ContentTypeApp   string      `json:"contentTypeApp"`
	ContentTypeID    int         `json:"contentTypeId"`
	URL              string      `json:"url"`
	String           string      `json:"string"`
}

type NotificationRecipient struct {
	ID int `json:"id"`
}

type NotificationActionObject struct {
	PK               int    `json:"pk,omitempty"`
	ContentTypeName  string `json:"contentTypeName,omitempty"`
	ContentTypeModel string `json:"contentTypeModel,omitempty"`
	ContentTypeApp   string `json:"contentTypeApp,omitempty"`
	ContentTypeId    int    `json:"contentTypeId,omitempty"`
	URL              string `json:"url,omitempty"`
	String           string `json:"string,omitempty"`
}

type NotificationData struct {
	Count   int            `json:"count"`
	Next    string         `json:"next"`
	Prev    string         `json:"previous"`
	Results []Notification `json:"results"`
}

type Disclaimer struct {
	ValidFrom string `json:"validFrom"`
	ValidTo   string `json:"validTo"`
	Priority  int    `json:"priority"`
	Message   string `json:"message"`
	URL       string `json:"url"`
	Slug      string `json:"slug"`
}

type DisclaimerData struct {
	Count    int          `json:"count"`
	Next     string       `json:"next"`
	Previous string       `json:"previous"`
	Results  []Disclaimer `json:"results"`
}

type DownloadThumbnailData struct {
	AddonVersion    string `json:"addon_version"`
	PlatformVersion string `json:"platform_version"`
	ThumbnailType   string `json:"thumbnail_type"`
	ImagePath       string `json:"image_path"`
	ImageURL        string `json:"image_url"`
	AssetBaseID     string `json:"assetBaseId"`
	Index           int    `json:"index"`
}

type SearchTaskData struct {
	PREFS           `json:"PREFS"`
	AddonVersion    string `json:"addon_version"`
	PlatformVersion string `json:"platform_version"`
	APIKey          string `json:"api_key"`
	AppID           int    `json:"app_id"`
	AssetType       string `json:"asset_type"`
	BlenderVersion  string `json:"blender_version"`
	GetNext         bool   `json:"get_next"`
	NextURL         string `json:"next"`
	PageSize        int    `json:"page_size"`
	SceneUUID       string `json:"scene_uuid"`
	TempDir         string `json:"tempdir"`
	URLQuery        string `json:"urlquery"`
	IsValidator     bool   `json:"is_validator"` // is true for validators, so we can do immediate hacks in the Client right after the search results come
}

type ReportData struct {
	AppID int `json:"app_id"` // AppID is PID of Blender in which add-on runs
}
