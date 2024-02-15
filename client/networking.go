package main

import "net/http"

func DebugNetworkHandler(w http.ResponseWriter, r *http.Request) {
	text := "Network Debug not implemented now."
	w.Write([]byte(text))
	w.WriteHeader(http.StatusOK)
}
