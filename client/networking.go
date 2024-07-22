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
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"net/url"
	"os"
	"time"

	"github.com/rapid7/go-get-proxied/proxy"
)

func DebugNetworkHandler(w http.ResponseWriter, r *http.Request) {
	report := NetworkDebug()

	w.Header().Set("Content-Type", "text/plain")
	w.Write([]byte(report))
}

// CreateHTTPClients creates HTTP clients with proxy settings, assings them to global variables.
// Handles errors gracefully - if any error occurs setting up proxy, it will just default to no proxy.
func CreateHTTPClients(proxyURL, proxyWhich, sslContext, trustedCACerts string) {
	proxy := GetProxyFunc(proxyURL, proxyWhich)
	tlsConfig := GetTLSConfig(sslContext)
	tlsConfig.RootCAs = GetCACertPool(trustedCACerts)

	ClientAPI = GetHTTPClient(nil, tlsConfig, proxy, time.Minute)
	ClientDownloads = GetHTTPClient(nil, tlsConfig, proxy, 1*time.Hour)
	ClientUploads = GetHTTPClient(nil, tlsConfig, proxy, 24*time.Hour)
	ClientBigThumbs = GetHTTPClient(nil, tlsConfig, proxy, time.Minute)
	ClientSmallThumbs = GetHTTPClient(nil, tlsConfig, proxy, time.Minute)
}

func GetHTTPClient(transport *http.Transport, tlsConfig *tls.Config, proxy func(*http.Request) (*url.URL, error), timeout time.Duration) *http.Client {
	if transport == nil {
		transport = http.DefaultTransport.(*http.Transport).Clone()
	}
	transport.TLSClientConfig = tlsConfig
	transport.Proxy = proxy

	return &http.Client{
		Transport: http.DefaultTransport,
		Timeout:   timeout,
	}
}

// GetProxyFunc returns a function that can be used as a proxy for HTTP client.
func GetProxyFunc(proxyURL, proxyWhich string) func(*http.Request) (*url.URL, error) {
	var noProxy func(*http.Request) (*url.URL, error)
	switch proxyWhich {
	case "SYSTEM":
		BKLog.Printf("%s Using proxy settings from system network settings", EmoOK)
		p := proxy.NewProvider("").GetProxy("https", "https://blenderkit.com")
		if p == nil {
			return noProxy
		}
		return http.ProxyURL(p.URL())
	case "ENVIRONMENT":
		BKLog.Printf("%s Using proxy settings only from environment variables HTTP_PROXY and HTTPS_PROXY", EmoOK)
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

	return noProxy
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

func GetIP() (string, error) {
	resp, err := http.Get("https://api.ipify.org?format=json")
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()

	var ip struct {
		IP string `json:"ip"`
	}

	err = json.NewDecoder(resp.Body).Decode(&ip)
	if err != nil {
		return "127.0.0.1", err
	}
	return ip.IP, nil
}

var UserAgentList = []string{
	"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
	"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
	//"Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
	//"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0",
	//"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
	"",
}

//"headers": {
//    "Accept": "application/json",
//    "Accept-Encoding": "gzip, deflate",
//    "Accept-Language": "en-US,en;q=0.5",
//    "Host": "httpbin.org",
//    "Priority": "u=0",
//    "Referer": "http://httpbin.org/",
//    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:128.0) Gecko/20100101 Firefox/128.0",
//    "X-Amzn-Trace-Id": "Root=1-669e49f6-6a223d0b7b77e869286d13fe"
//  },

var sslOptions = []string{
	"ENABLED",
	"DISABLED",
}

var proxyOptions = []string{
	"SYSTEM",
	"ENVIRONMENT",
	"NONE",
}

var TimeoutCoefficient = []int{1, 10}

func NetworkDebug() string {
	report := fmt.Sprintf("NETWORK DEBUG REPORT\nPlatform: %s\nClientVersion: %s\nSystemID %s\n", GetPlatformVersion(), ClientVersion, *getSystemID())
	BKLog.Printf("%s Network debug has started", EmoDebug)

	ip, err := GetIP()
	if err != nil {
		fmt.Println(err)
		return fmt.Sprintf("Error getting client's IP: %v", err)
	}
	BKLog.Printf("%s Client's IP: %s", EmoDebug, ip)
	report += fmt.Sprintf("Client's IP: %s\n", ip)
	report += "-----------------------------------\n\n"

	for tCoefficient := range TimeoutCoefficient {
		tq := time.Duration(TimeoutCoefficient[tCoefficient])
		transport := http.DefaultTransport.(*http.Transport).Clone()
		transport.IdleConnTimeout = 90 * time.Second * tq
		transport.TLSHandshakeTimeout = 10 * time.Second * tq
		transport.ExpectContinueTimeout = 1 * time.Second * tq
		transport.DialContext = (&net.Dialer{
			Timeout:   30 * time.Second * tq,
			KeepAlive: 30 * time.Second * tq,
		}).DialContext

		for sslOption := range sslOptions {
			tlsConfig := GetTLSConfig(sslOptions[sslOption])

			for proxyOption := range proxyOptions {
				proxy := GetProxyFunc("", proxyOptions[proxyOption])
				timeout := time.Duration(1 * time.Minute * tq)
				client := GetHTTPClient(transport, tlsConfig, proxy, timeout)

				for agent := range UserAgentList {
					agentString := UserAgentList[agent]
					report += DebugRequest(client, agentString, TimeoutCoefficient[tCoefficient], sslOptions[sslOption], proxyOptions[proxyOption])
				}
			}
		}
	}

	return report
}

func DebugRequest(client *http.Client, agent string, tCoeff int, sslOption string, proxyOption string) string {
	report := fmt.Sprintf("=== DEBUG REQUEST (timeCoef=%d, sslOption=\"%s\", proxyOption=\"%s\", agent=\"%s\")\n", tCoeff, sslOption, proxyOption, agent)
	req, err := http.NewRequest("GET", "https://www.blenderkit.com/api/v1/search/?query=kitten", nil)
	if err != nil {
		msg := fmt.Sprintf("Error creating request: %v", err)
		return report + msg
	}

	platformVersion := GetPlatformVersion()
	req.Header = getHeaders("", *SystemID, *AddonVersion, platformVersion)
	if agent != "" {
		req.Header.Set("User-Agent", agent)
	}

	resp, err := client.Do(req)
	if err != nil {
		msg := fmt.Sprintf("Error doing request: %v", err)
		return report + msg
	}
	defer resp.Body.Close()

	BKLog.Printf(`%s %s
timeQ=%v
sslOption=%s,
proxyOption=%s,
agent=%s`,
		EmoDebug,
		resp.Status,
		tCoeff,
		sslOption,
		proxyOption,
		agent,
	)

	report += fmt.Sprintf("    %s\n\n", resp.Status)

	return report
}
