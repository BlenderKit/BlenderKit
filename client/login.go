package main

import (
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/url"
	"strings"

	"github.com/google/uuid"
)

type OAuth2VerificationData struct {
	MinimalTaskData
	CodeVerifier string `json:"code_verifier"`
	State        string `json:"state"`
}

// Handles Code Verifier and State parameters exchange for OAuth2 verfication.
// Add-on creates PKCE pair (Code Chalange + Code Verifier) and sends its code_verifier to Client so it can later verify the response from server.
// Random state string is also generated and send to the Client.
// Once add-on get response from here, it opens BlenderKit.com with code_challenge + state parameters with URL redirect to localhost:port/consumer/exchange.
// Server verifies user's login and redirects the browser to URL redirect which lands on func consumerExchangeHandler().
// This func later checks the response against code_verifier and state parameters.
func OAuth2VerificationDataHandler(w http.ResponseWriter, r *http.Request) {
	var data OAuth2VerificationData
	err := json.NewDecoder(r.Body).Decode(&data)
	if err != nil {
		http.Error(w, "Error parsing JSON: "+err.Error(), http.StatusBadRequest)
		return
	}

	OAuth2SessionsMux.Lock()
	OAuth2Sessions[data.State] = data
	OAuth2SessionsMux.Unlock()
	BKLog.Printf("%s Add-on (%v) has created OAuth2 session (code_verifier=%s, state=%s).", EmoIdentity, data.AppID, data.CodeVerifier, data.State)
	w.WriteHeader(http.StatusOK)
}

// Handles the exchange of the authorization code for tokens.
// This is the URL that the server redirects the browser to after the user logs in.
func consumerExchangeHandler(w http.ResponseWriter, r *http.Request) {
	queryParams := r.URL.Query()
	authCode := queryParams.Get("code")
	state := queryParams.Get("state")
	redirectURL := *Server + "/oauth-landing/"
	if authCode == "" {
		http.Error(w, "Authorization Failed. OAuth2 authorization code was not provided.", http.StatusBadRequest)
		return
	}
	if state == "" {
		http.Error(w, "Authorization Failed. OAuth2 state was not provided.", http.StatusBadRequest)
		return
	}

	OAuth2SessionsMux.Lock()
	verificationData := OAuth2Sessions[state]
	OAuth2SessionsMux.Unlock()
	if verificationData.State != state {
		http.Error(w, "Authorization Failed. OAuth2 state does not match.", http.StatusBadRequest)
		return
	}

	responseJSON, status, error := GetTokens(authCode, "", verificationData)
	if status == -1 {
		text := "Authorization Failed. Server is not reachable. Response: " + error
		http.Error(w, text, http.StatusBadRequest)
		return
	}

	if status != 200 {
		text := fmt.Sprintf("Authorization Failed. Retrieval of tokens failed (status code: %d) Response: %v", status, error)
		http.Error(w, text, status)
		return
	}

	TasksMux.Lock()
	for appID := range Tasks {
		taskID := uuid.New().String()
		task := NewTask(make(map[string]interface{}), appID, taskID, "login")
		task.Result = responseJSON
		task.Finish("Tokens obtained")
		Tasks[appID][task.TaskID] = task
	}
	TasksMux.Unlock()

	http.Redirect(w, r, redirectURL, http.StatusPermanentRedirect)
}

// GetTokens sends a request to the server to get tokens. It returns the response JSON, status code and error message as string.
// Parameter authCode is the authorization code - if it's not empty, it's used to get the tokens in grant_type "authorization_code".
// Parameter refreshToken is the refresh token - if it's not empty, it's used to get the tokens in grant_type "refresh_token".
// Must be called with either authCode or refreshToken, not both.
func GetTokens(authCode string, refreshToken string, verificationData OAuth2VerificationData) (map[string]interface{}, int, string) {
	if authCode == "" && refreshToken == "" {
		return nil, -1, "No authCode or refreshToken provided"
	}
	if authCode != "" && refreshToken != "" {
		return nil, -1, "Both authCode and refreshToken provided"
	}
	data := url.Values{}

	// If authCode is not empty, we are getting tokens for the first time.
	if authCode != "" {
		data.Set("grant_type", "authorization_code")
		data.Set("code", authCode)

		if verificationData.CodeVerifier != "" {
			data.Set("code_verifier", verificationData.CodeVerifier)
		} else {
			return nil, -1, "Could not find code_verifier."
		}
	}

	// If refreshToken is not empty, we are refreshing the tokens.
	if refreshToken != "" {
		data.Set("grant_type", "refresh_token")
		data.Set("refresh_token", refreshToken)
	}

	data.Set("client_id", OAUTH_CLIENT_ID)
	data.Set("scopes", "read write")
	data.Set("redirect_uri", fmt.Sprintf("http://localhost:%s/consumer/exchange/", *Port))

	url := fmt.Sprintf("%s/o/token/", *Server)
	req, err := http.NewRequest("POST", url, strings.NewReader(data.Encode()))
	if err != nil {
		log.Fatalf("Error creating request: %v", err)
		return nil, -1, "Failed to create request"
	}

	req.Header = getHeaders("", *SystemID, verificationData.AddonVersion, verificationData.PlatformVersion)
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded") // Overwrite Content-Type to "application/x-www-form-urlencoded"
	resp, err := ClientAPI.Do(req)
	if err != nil {
		log.Printf("Error making request: %v", err)
		return nil, -1, "Failed to make request"
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		log.Printf("Error reading response: %v", err)
		return nil, resp.StatusCode, "Failed to read response"
	}

	if resp.StatusCode != http.StatusOK {
		log.Printf("Error response from server: %s", string(body))
		return nil, resp.StatusCode, "Failed to retrieve tokens"
	}

	var respJSON map[string]interface{}
	if err := json.Unmarshal(body, &respJSON); err != nil {
		log.Printf("Error decoding response JSON: %v", err)
		return nil, resp.StatusCode, "Failed to decode response JSON"
	}

	BKLog.Printf("%s Token retrieval OK (grant type: %s)", EmoIdentity, data.Get("grant_type"))
	return respJSON, resp.StatusCode, ""
}

type RefreshTokenData struct {
	MinimalTaskData
	RefreshToken string `json:"refresh_token"` // Refresh token to be used to get new tokens
}

// RefreshTokenHandler handles the request to refresh the access token.
// It parses the request body, calls goroutine RefreshToken and returns StatusOK.
// If the request body is invalid, it returns StatusBadRequest.
func RefreshTokenHandler(w http.ResponseWriter, r *http.Request) {
	body, err := io.ReadAll(r.Body)
	if err != nil {
		http.Error(w, "Error reading request body: "+err.Error(), http.StatusInternalServerError)
		return
	}
	defer r.Body.Close()

	var data RefreshTokenData
	err = json.Unmarshal(body, &data)
	if err != nil {
		http.Error(w, "Error parsing JSON: "+err.Error(), http.StatusBadRequest)
		return
	}

	go RefreshToken(data)
	w.WriteHeader(http.StatusOK)
}

// RefreshToken refreshes the access token using the refresh token. It calls GetTokens with the refresh token and "refresh_token" grant type.
// If the request is successful, it creates Tasks with status finished for all appIDs with the response JSON -> refreshing the token in all add-ons.
// If the request fails, it creates Tasks with status error for all appIDs -> logout in all add-ons.
func RefreshToken(data RefreshTokenData) {
	verificationData := OAuth2VerificationData{
		State:        "",
		CodeVerifier: "",
		MinimalTaskData: MinimalTaskData{
			AppID:           data.AppID,
			APIKey:          data.APIKey,
			AddonVersion:    data.AddonVersion,
			PlatformVersion: data.PlatformVersion,
		},
	}
	rJSON, status, errMsg := GetTokens("", data.RefreshToken, verificationData)
	TasksMux.Lock()
	for appID := range Tasks {
		taskID := uuid.New().String()
		task := NewTask(make(map[string]interface{}), appID, taskID, "login")
		task.Result = rJSON
		if errMsg != "" || status != http.StatusOK {
			task.Message = fmt.Sprintf("Failed to refresh token: %v", errMsg)
			task.Status = "error"
		} else {
			task.Message = "Refreshed tokens obtained"
			task.Status = "finished"
		}
		Tasks[appID][task.TaskID] = task
	}
	TasksMux.Unlock()
}
