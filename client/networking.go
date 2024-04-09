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
	"crypto/x509"
	"net/http"
	"net/url"
	"os"
	"time"
)

func DebugNetworkHandler(w http.ResponseWriter, r *http.Request) {
	text := "Network Debug not implemented now."
	w.Write([]byte(text))
	w.WriteHeader(http.StatusOK)
}

// CreateHTTPClients creates HTTP clients with proxy settings, assings them to global variables.
// Handles errors gracefully - if any error occurs setting up proxy, it will just default to no proxy.
func CreateHTTPClients(proxyURL, proxyWhich, sslContext, trustedCACerts string) {
	proxy := GetProxyFunc(proxyURL, proxyWhich)
	tlsConfig := GetTLSConfig(sslContext)
	tlsConfig.RootCAs = GetCACertPool(trustedCACerts)

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

// GetProxyFunc returns a function that can be used as a proxy for HTTP client.
func GetProxyFunc(proxyURL, proxyWhich string) func(*http.Request) (*url.URL, error) {
	switch proxyWhich {
	case "SYSTEM":
		BKLog.Printf("%s Using system proxy settings", EmoOK)
		return http.ProxyFromEnvironment
	case "CUSTOM":
		pURL, err := url.Parse(proxyURL)
		if err != nil {
			BKLog.Printf("%s Defaulting to no proxy settings, error parsing custom proxy URL: %v", EmoWarning, err)
			break
		}
		BKLog.Printf("%s Using custom proxy: %v", EmoOK, proxyURL)
		return http.ProxyURL(pURL)
	case "NONE":
		BKLog.Printf("%s Using no proxy", EmoOK)
	default:
		BKLog.Printf("%s Defaulting to no proxy due to - unrecognized proxy_which parameter: %v", EmoOK, proxyWhich)
	}

	var proxy func(*http.Request) (*url.URL, error)
	return proxy
}

func GetTLSConfig(sslContext string) *tls.Config {
	switch sslContext {
	case "ENABLED":
		BKLog.Printf("%s SSL verification is enabled", EmoSecure)
		return &tls.Config{}
	case "DISABLED":
		BKLog.Printf("%s SSL verification disabled, insecure!", EmoInsecure)
		return &tls.Config{InsecureSkipVerify: true}
	default:
		BKLog.Printf("%s Defaulting to enabled SSL verification due to - unrecognized ssl_context parameter: %v", EmoSecure, sslContext)
		return &tls.Config{}
	}
}

func GetCACertPool(caFilePath string) *x509.CertPool {
	caCertPool, err := x509.SystemCertPool()
	if err != nil {
		BKLog.Printf("%s Error loading system cert pool of CA certificates: %v", EmoWarning, err)
		caCertPool = x509.NewCertPool()
	}

	if caFilePath == "" {
		return caCertPool
	}

	caCert, err := os.ReadFile(caFilePath)
	if err != nil {
		BKLog.Printf("%s Error reading CA certificate: %v", EmoWarning, err)
		return caCertPool
	}

	BKLog.Printf("%s Loaded CA certificate from file: %v", EmoOK, caFilePath)
	caCertPool.AppendCertsFromPEM(caCert)
	return caCertPool
}
