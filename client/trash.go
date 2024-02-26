// This file is a trash file - in final implementation, we will remove most of the code in this file
package main

import (
	"encoding/hex"
	"fmt"
	"net"
)

// fakePythonUUIDGetNode is a fake implementation of the Python uuid.getnode() function
// It returns the MAC address of the first non-loopback, up network interface as a string
// We could replace this by more robust machineid.ProtectedID("blenderkit-client") from package github.com/denisbrodbeck/machineid
func fakePythonUUIDGetNode() (*string, error) {
	mac, err := getMACAddress()
	if err != nil {
		return nil, err
	}
	macInt, err := macAddressToInt(mac)
	if err != nil {
		return nil, err
	}
	id := fmt.Sprintf("%d", macInt-1) // for some reason, the original code subtracts 1 from the MAC address
	return &id, nil
}

// getMACAddress returns the MAC address of the first non-loopback, up network interface
func getMACAddress() (string, error) {
	interfaces, err := net.Interfaces()
	if err != nil {
		return "", err
	}
	for _, iface := range interfaces {
		if iface.Flags&net.FlagLoopback == 0 && iface.Flags&net.FlagUp != 0 {
			if addr := iface.HardwareAddr.String(); addr != "" {
				return addr, nil
			}
		}
	}
	return "", fmt.Errorf("no non-loopback, up network interfaces found")
}

// macAddressToInt converts a MAC address string to a 48-bit integer
func macAddressToInt(macStr string) (uint64, error) {
	// Parse the MAC address string to net.HardwareAddr
	hwAddr, err := net.ParseMAC(macStr)
	if err != nil {
		return 0, err
	}

	// MAC address should be 6 bytes (48 bits) long
	if len(hwAddr) != 6 {
		return 0, fmt.Errorf("invalid MAC address length")
	}

	// Convert net.HardwareAddr (byte slice) to hex string without colons
	hexStr := hex.EncodeToString(hwAddr)

	// Convert hex string to uint64
	macInt, err := hex.DecodeString(hexStr)
	if err != nil {
		return 0, err
	}

	// Since DecodeString returns a byte slice and we know it will be exactly 6 bytes,
	// we can convert it directly to a 48-bit integer.
	var intResult uint64
	for _, b := range macInt {
		intResult = (intResult << 8) + uint64(b)
	}

	return intResult, nil
}
