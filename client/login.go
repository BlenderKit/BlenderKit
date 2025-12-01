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
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"sync"

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

	responseJSON, status, errMsg, errDetails := GetTokens(authCode, "", verificationData)
	if status == -1 {
		text := fmt.Sprintf("Authorization Failed - wrong request parameters: %s%s", errMsg, errDetails) // errDetails is "" or ", text text..."
		http.Error(w, text, http.StatusBadRequest)
		return
	}

	if status != 200 {
		text := fmt.Sprintf("Authorization Failed - request failed: %s%s", errMsg, errDetails)
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
// Returns response JSON, status code (-1 for wrong authCode/refreshToken/verificationData, or directly HTTP status code), error message and error details ("" or ", text text...").
func GetTokens(authCode string, refreshToken string, verificationData OAuth2VerificationData) (map[string]interface{}, int, string, string) {
	if authCode == "" && refreshToken == "" {
		errMsg := "No authCode or refreshToken provided"
		BKLog.Printf("%s %s", EmoError, errMsg)
		return nil, -1, errMsg, ""
	}
	if authCode != "" && refreshToken != "" {
		errMsg := "Both authCode and refreshToken provided"
		BKLog.Printf("%s %s", EmoError, errMsg)
		return nil, -1, errMsg, ""
	}
	data := url.Values{}

	// If authCode is not empty, we are getting tokens for the first time.
	if authCode != "" {
		data.Set("grant_type", "authorization_code")
		data.Set("code", authCode)

		if verificationData.CodeVerifier != "" {
			data.Set("code_verifier", verificationData.CodeVerifier)
		} else {
			errMsg := "Could not find code_verifier"
			BKLog.Printf("%s %s", EmoError, errMsg)
			return nil, -1, errMsg, ""
		}
	}

	// If refreshToken is not empty, we are refreshing the tokens.
	if refreshToken != "" {
		data.Set("grant_type", "refresh_token")
		data.Set("refresh_token", refreshToken)
	}

	data.Set("client_id", OAUTH_CLIENT_ID)
	data.Set("scopes", "read write")
	data.Set("redirect_uri", fmt.Sprintf("http://localhost:%s/consumer/exchange/", *Port)) // /vX.Y/ prefix not used as server does not support regex for redirect paths

	url := fmt.Sprintf("%s/o/token/", *Server)
	req, err := http.NewRequest("POST", url, strings.NewReader(data.Encode()))
	if err != nil {
		errMsg := fmt.Sprintf("Request initialization error: %v", err)
		details := fmt.Sprintf(", request: %v", req)
		BKLog.Printf("%s %s%s", EmoError, errMsg, details)
		return nil, -1, errMsg, details
	}

	req.Header = getHeaders("", *SystemID, verificationData.AddonVersion, verificationData.PlatformVersion) // Does not make sense to send old API key here
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")                                     // Overwrite Content-Type to "application/x-www-form-urlencoded"
	resp, err := ClientAPI.Do(req)
	if err != nil {
		errMsg := fmt.Sprintf("Making request error: %v", err)
		details := fmt.Sprintf(", response: %v", resp)
		BKLog.Printf("%s %s%s", EmoError, errMsg, details)
		return nil, -1, errMsg, details
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		errMsg := fmt.Sprintf("Reading response body error: %v", err)
		details := fmt.Sprintf(", response: %v, body: %s", resp, string(body))
		BKLog.Printf("%s %s%s", EmoError, errMsg, details)
		return nil, resp.StatusCode, errMsg, details
	}

	if resp.StatusCode != http.StatusOK {
		errMsg := fmt.Sprintf("Wrong response status: %s", resp.Status)
		details := fmt.Sprintf(", response: %v, body: %s", resp, string(body))
		BKLog.Printf("%s %s%s", EmoError, errMsg, details)
		return nil, resp.StatusCode, errMsg, details
	}

	var respJSON map[string]interface{}
	err = json.Unmarshal(body, &respJSON)
	if err != nil {
		errMsg := fmt.Sprintf("Error decoding response JSON: %v", err)
		details := fmt.Sprintf(", response: %v, body: %s", resp, string(body))
		BKLog.Printf("%s %s%s", EmoError, errMsg, details)
		return nil, resp.StatusCode, errMsg, details
	}

	BKLog.Printf("%s Token retrieval OK (grant type: %s)", EmoIdentity, data.Get("grant_type"))
	return respJSON, resp.StatusCode, "", ""
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
	rJSON, status, errMsg, errDetails := GetTokens("", data.RefreshToken, verificationData)
	TasksMux.Lock()
	for appID := range Tasks {
		taskID := uuid.New().String()
		task := NewTask(make(map[string]interface{}), appID, taskID, "login")
		task.Result = rJSON
		if errMsg != "" || status != http.StatusOK {
			task.Message = fmt.Sprintf("Failed to refresh token: %v", errMsg)
			task.MessageDetailed = errDetails
			task.Status = "error"
		} else {
			task.Message = "Refreshed tokens obtained"
			task.Status = "finished"
		}
		Tasks[appID][task.TaskID] = task
	}
	TasksMux.Unlock()
}

// OAuth2LogoutHandler handles the request signaling that the user has logged out.
// It devalidates the
func OAuth2LogoutHandler(w http.ResponseWriter, r *http.Request) {
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
	go OAuth2Logout(data)

	w.WriteHeader(http.StatusOK)
}

// OAuth2Logout sends revocation request to the server to revoke the tokens.
// It logs out the user from all add-ons.
func OAuth2Logout(data RefreshTokenData) {
	var wg sync.WaitGroup
	var ch = make(chan error, 2)
	wg.Add(2)
	go RevokeOAuth2Token(data, "api_key", ch, &wg)
	go RevokeOAuth2Token(data, "refresh_token", ch, &wg)
	wg.Wait()
	close(ch)
	var errors []error
	for err := range ch {
		if err != nil {
			errors = append(errors, err)
		}
	}

	var message, status string
	if len(errors) == 0 {
		message = "Logout OK, tokens successfully revoked on the server"
		status = "finished"
	} else if len(errors) == 1 {
		message = fmt.Sprintf("Logout partially OK, failed to revoke token: %v", errors[0])
		status = "error"
	} else {
		message = fmt.Sprintf("Logout partially OK, failed to revoke tokens: %v", errors)
		status = "error"
	}

	TasksMux.Lock()
	for appID := range Tasks {
		task := NewTask(data, appID, uuid.New().String(), "oauth2/logout")
		task.Message = message
		task.Status = status
		task.Error = fmt.Errorf("%s", message) // just to print it into console
		AddTaskCh <- task
	}
	TasksMux.Unlock()
}

// RevokeOAuth2Token revokes api_key or refresh_token according to RFC 7009: https://www.rfc-editor.org/rfc/rfc7009.html#section-2.1.
// Token type is either "api_key" or "refresh_token".
func RevokeOAuth2Token(data RefreshTokenData, tokenType string, ch chan error, wg *sync.WaitGroup) {
	defer wg.Done()
	rData := url.Values{}
	rData.Set("client_id", OAUTH_CLIENT_ID)
	if tokenType == "api_key" {
		rData.Set("token", data.APIKey)
	} else if tokenType == "refresh_token" {
		rData.Set("token", data.RefreshToken)
		rData.Set("token_type_hint", "refresh_token")
	} else {
		ch <- fmt.Errorf("invalid token type: %s", tokenType)
		return
	}

	req, err := http.NewRequest("POST", fmt.Sprintf("%s/o/revoke_token/", *Server), strings.NewReader(rData.Encode()))
	if err != nil {
		ch <- fmt.Errorf("'%v: %w'", tokenType, err)
		return
	}

	req.Header = getHeaders("", *SystemID, data.AddonVersion, data.PlatformVersion)
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded") // Overwrite Content-Type to "application/x-www-form-urlencoded"
	resp, err := ClientAPI.Do(req)
	if err != nil {
		ch <- fmt.Errorf("'%v: %w'", tokenType, err)
		return
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		ch <- fmt.Errorf("'%v: %w'", tokenType, err)
		return
	}

	if resp.StatusCode != http.StatusOK {
		ch <- fmt.Errorf("'%v: error response (%v) from server: %s'", tokenType, resp.StatusCode, string(body))
		return
	}

	BKLog.Printf("%v %v revoked successfully", EmoIdentity, tokenType)
	ch <- nil
}
