package login

import (
	"fmt"
	"net/http"
	"yourapp/daemon_globals"
	"yourapp/daemon_oauth"
	"yourapp/daemon_tasks"
)

func ConsumerExchange(w http.ResponseWriter, r *http.Request) {
	authCode := r.URL.Query().Get("code")
	redirectURL := fmt.Sprintf("%s/oauth-landing/", daemon_globals.Server)

	if authCode == "" {
		http.Error(w, "Authorization Failed. Authorization code was not provided.", http.StatusBadRequest)
		return
	}

	responseJSON, status, err := daemon_oauth.GetTokens(r, authCode)
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

	for _, appID := range daemon_globals.ActiveApps {
		task := daemon_tasks.NewTask(nil, appID, "login", "Getting authorization code")
		daemon_globals.Tasks = append(daemon_globals.Tasks, task)
		task.Result = responseJSON
		task.Finished("Tokens obtained")
	}

	http.Redirect(w, r, redirectURL, http.StatusPermanentRedirect)
}
