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

// Handles code_verifier exchange: add-on creates PKCE pair and sends its code_challenge to daemon so it can later verify the response from server.
// Once add-on get response from here, it opens BlenderKit.com with code_challenge and URL redirect to localhost:port/consumer/exchange.
// Server verifies user's login and redirects the browser to URL redirect which lands on func consumerExchangeHandler().
func CodeVerifierHandler(w http.ResponseWriter, r *http.Request) {
	rJSON := make(map[string]interface{})
	if err := json.NewDecoder(r.Body).Decode(&rJSON); err != nil {
		http.Error(w, "Error parsing JSON: "+err.Error(), http.StatusBadRequest)
		return
	}

	cv, ok := rJSON["code_verifier"].(string)
	if !ok {
		http.Error(w, "Invalid or missing 'code_verifier' in JSON", http.StatusBadRequest)
		return
	}

	CodeVerifierMux.Lock()
	CodeVerifier = cv
	CodeVerifierMux.Unlock()
	fmt.Printf("Code verifier set: %v\n", CodeVerifier)
	w.WriteHeader(http.StatusOK)
}

// Handles the exchange of the authorization code for tokens. This is the URL that the server redirects the browser to after the user logs in.
func consumerExchangeHandler(w http.ResponseWriter, r *http.Request) {
	queryParams := r.URL.Query()
	authCode := queryParams.Get("code")
	redirectURL := *Server + "/oauth-landing/"
	if authCode == "" {
		http.Error(w, "Authorization Failed. Authorization code was not provided.", http.StatusBadRequest)
		return
	}

	responseJSON, status, error := GetTokens(authCode, "")
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
func GetTokens(authCode string, refreshToken string) (map[string]interface{}, int, string) {
	data := url.Values{}
	var grantType string
	if authCode != "" {
		grantType = "authorization_code"
		data.Set("code", authCode)
		CodeVerifierMux.Lock()
		defer CodeVerifierMux.Unlock()
		if CodeVerifier != "" {
			data.Set("code_verifier", CodeVerifier)
		} else {
			return nil, -1, "Could not find code_verifier."
		}
	} else if refreshToken != "" {
		grantType = "refresh_token"
		data.Set("refresh_token", refreshToken)
	} else {
		return nil, -1, "No authCode or refreshToken provided"
	}

	data.Set("grant_type", grantType)
	data.Set("client_id", OAUTH_CLIENT_ID)
	data.Set("scopes", "read write")
	data.Set("redirect_uri", fmt.Sprintf("http://localhost:%s/consumer/exchange/", *Port))

	url := fmt.Sprintf("%s/o/token/", *Server)
	headers := getHeaders("", *SystemID) // Ensure this sets Content-Type to "application/x-www-form-urlencoded"
	req, err := http.NewRequest("POST", url, strings.NewReader(data.Encode()))
	if err != nil {
		log.Fatalf("Error creating request: %v", err)
	}
	// Set the Content-Type for form-encoded data
	req.Header = headers
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
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

	log.Printf("Token retrieval OK (grant type: %s)", grantType)
	return respJSON, resp.StatusCode, ""
}

type RefreshTokenData struct {
	RefreshToken string `json:"refresh_token"`
	OldAPIKey    string `json:"old_api_key"`
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
	rJSON, status, errMsg := GetTokens("", data.RefreshToken)
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
