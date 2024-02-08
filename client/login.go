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
func codeVerifierHandler(w http.ResponseWriter, r *http.Request) {
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

	responseJSON, status, error := GetTokens(r, authCode, "", "authorization_code")
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

func GetTokens(r *http.Request, authCode string, refreshToken string, grantType string) (map[string]interface{}, int, string) {
	data := url.Values{}
	data.Set("grant_type", grantType)
	data.Set("client_id", OAUTH_CLIENT_ID)
	data.Set("scopes", "read write")
	data.Set("redirect_uri", fmt.Sprintf("http://localhost:%s/consumer/exchange/", *Port))
	if CodeVerifier != "" {
		CodeVerifierMux.Lock()
		data.Set("code_verifier", CodeVerifier)
		CodeVerifierMux.Unlock()
	} else {
		fmt.Println("Code verifier missing.")
	}
	if authCode != "" {
		data.Set("code", authCode)
	}
	if refreshToken != "" {
		data.Set("refresh_token", refreshToken)
	}

	url := fmt.Sprintf("%s/o/token/", *Server)
	session := http.Client{}
	headers := getHeaders("", SystemID) // Ensure this sets Content-Type to "application/x-www-form-urlencoded"
	req, err := http.NewRequest("POST", url, strings.NewReader(data.Encode()))
	if err != nil {
		log.Fatalf("Error creating request: %v", err)
	}
	// Set the Content-Type for form-encoded data
	req.Header = headers
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")

	fmt.Print("Sending request to ", url, " with data: ", data.Encode(), " and headers:", req.Header, "\n")
	resp, err := session.Do(req)
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

	log.Println("Token retrieval OK.")
	return respJSON, resp.StatusCode, ""
}
