package main

import (
	"fmt"
	"net/http"
)

func ConsumerExchange(w http.ResponseWriter, r *http.Request) {
	authCode := r.URL.Query().Get("code")
	redirectURL := fmt.Sprintf("%s/oauth-landing/", Server)

	if authCode == "" {
		http.Error(w, "Authorization Failed. Authorization code was not provided.", http.StatusBadRequest)
		return
	}

	_, status, err := GetTokens(r, authCode)
	if status == -1 {
		text := fmt.Sprintf("Authorization Failed. Server is not reachable. Response: %v", err)
		// Handling of SSL certificates and errors omitted
		http.Error(w, text, http.StatusInternalServerError)
		return
	}

	if status != http.StatusOK {
		text := fmt.Sprintf("Authorization Failed. Retrieval of tokens failed (status code: %d). Response: %v", status, err)
		// Handling of SSL certificates and errors omitted
		http.Error(w, text, http.StatusInternalServerError)
		return
	}

	//for _, _ := range ActiveApps {
	//	task := NewTask(nil, appID, "login", "Getting authorization code")

	//	task.Result = responseJSON
	//	task.Finished("Tokens obtained", "")
	//}

	http.Redirect(w, r, redirectURL, http.StatusPermanentRedirect)
}

func GetTokens(r *http.Request, authCode string) (map[string]interface{}, int, error) {
	return nil, -1, nil
}
