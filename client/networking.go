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
	"crypto/tls"
	"net/http"
	"net/url"
	"time"
)

func DebugNetworkHandler(w http.ResponseWriter, r *http.Request) {
	text := "Network Debug not implemented now."
	w.Write([]byte(text))
	w.WriteHeader(http.StatusOK)
}

// CreateHTTPClients creates HTTP clients with proxy settings, assings them to global variables.
// Handles errors gracefully - if any error occurs setting up proxy, it will just default to no proxy.
func CreateHTTPClients(proxyURL, proxyWhich, sslContext string) {
	var proxy func(*http.Request) (*url.URL, error)
	switch proxyWhich {
	case "SYSTEM":
		proxy = http.ProxyFromEnvironment
		BKLog.Printf("%s Using system proxy settings", EmoOK)
	case "CUSTOM":
		pURL, err := url.Parse(proxyURL)
		if err != nil {
			BKLog.Printf("%s Defaulting to no proxy due to - error parsing proxy URL: %v", EmoWarning, err)
		} else {
			proxy = http.ProxyURL(pURL)
			BKLog.Printf("%s Using custom proxy: %v", EmoOK, proxyURL)
		}
	case "NONE":
		BKLog.Printf("%s Using no proxy", EmoOK)
	default:
		BKLog.Printf("%s Defaulting to no proxy due to - unrecognized proxy_which parameter: %v", EmoOK, proxyWhich)
	}

	var tlsConfig *tls.Config
	switch sslContext {
	case "ENABLED":
		tlsConfig = &tls.Config{}
		BKLog.Printf("%s SSL verification is enabled", EmoSecure)
	case "DISABLED":
		tlsConfig = &tls.Config{InsecureSkipVerify: true}
		BKLog.Printf("%s SSL verification disabled, insecure!", EmoInsecure)
	default:
		tlsConfig = &tls.Config{}
		BKLog.Printf("%s Defaulting to enabled SSL verification due to - unrecognized ssl_context parameter: %v", EmoSecure, sslContext)
	}

	tAPI := http.DefaultTransport.(*http.Transport).Clone()
	tAPI.TLSClientConfig = tlsConfig
	tAPI.Proxy = proxy
	ClientAPI = &http.Client{
		Transport: tAPI,
		Timeout:   time.Minute,
	}

	tDownloads := http.DefaultTransport.(*http.Transport).Clone()
	tDownloads.TLSClientConfig = tlsConfig
	tDownloads.Proxy = proxy
	ClientDownloads = &http.Client{
		Transport: tDownloads,
		Timeout:   1 * time.Hour,
	}

	tUploads := http.DefaultTransport.(*http.Transport).Clone()
	tUploads.TLSClientConfig = tlsConfig
	tUploads.Proxy = proxy
	ClientUploads = &http.Client{
		Transport: tUploads,
		Timeout:   24 * time.Hour,
	}

	tBigThumbs := http.DefaultTransport.(*http.Transport).Clone()
	tBigThumbs.TLSClientConfig = tlsConfig
	tBigThumbs.Proxy = proxy
	ClientBigThumbs = &http.Client{
		Transport: tBigThumbs,
		Timeout:   time.Minute,
	}

	tSmallThumbs := http.DefaultTransport.(*http.Transport).Clone()
	tSmallThumbs.TLSClientConfig = tlsConfig
	tSmallThumbs.Proxy = proxy
	ClientSmallThumbs = &http.Client{
		Transport: tSmallThumbs,
		Timeout:   time.Minute,
	}
}
