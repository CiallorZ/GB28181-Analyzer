//go:build windows

// Build with -H windowsgui, then append the offline ZIP. archive/zip supports prefixed archives.
package main

import (
	"archive/zip"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"syscall"
	"unsafe"
)

var buildID string

func extract(z *zip.Reader, root string) error {
	for _, file := range z.File {
		name := filepath.FromSlash(file.Name)
		if !filepath.IsLocal(name) {
			return fmt.Errorf("invalid archive entry %q", name)
		}
		dest := filepath.Join(root, name)
		if file.FileInfo().IsDir() {
			if err := os.MkdirAll(dest, 0755); err != nil {
				return err
			}
			continue
		}
		if err := os.MkdirAll(filepath.Dir(dest), 0755); err != nil {
			return err
		}
		r, err := file.Open()
		if err != nil {
			return err
		}
		w, err := os.Create(dest)
		if err != nil {
			r.Close()
			return err
		}
		_, copyErr := io.Copy(w, r)
		err = errors.Join(copyErr, w.Close(), r.Close())
		if err != nil {
			return err
		}
	}
	return nil
}

func launch() error {
	if len(buildID) != 64 {
		return errors.New("missing package identity")
	}
	cache, err := os.UserCacheDir()
	if err != nil {
		return err
	}
	parent := filepath.Join(cache, "GB28181 Analyzer", "runtime")
	if err = os.MkdirAll(parent, 0755); err != nil {
		return err
	}
	root := filepath.Join(parent, buildID)
	if _, err = os.Stat(root); os.IsNotExist(err) {
		exe, err := os.Executable()
		if err != nil {
			return err
		}
		z, err := zip.OpenReader(exe)
		if err != nil {
			return err
		}
		defer z.Close()
		tmp, err := os.MkdirTemp(parent, "stage-")
		if err != nil {
			return err
		}
		defer os.RemoveAll(tmp)
		if err = extract(&z.Reader, tmp); err != nil {
			return err
		}
		acl := exec.Command(filepath.Join(os.Getenv("SystemRoot"), "System32", "icacls.exe"), filepath.Join(tmp, "WebView2"), "/grant", "*S-1-15-2-1:(OI)(CI)(RX)", "*S-1-15-2-2:(OI)(CI)(RX)")
		acl.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
		if err = acl.Run(); err != nil {
			return err
		}
		if err = os.Rename(tmp, root); err != nil {
			if _, other := os.Stat(root); other != nil {
				return err
			}
		}
	} else if err != nil {
		return err
	}
	for key, path := range map[string]string{"TSHARK_PATH": "Wireshark/tshark.exe", "CAPINFOS_PATH": "Wireshark/capinfos.exe", "DUMPCAP_PATH": "Wireshark/dumpcap.exe", "FFMPEG_PATH": "ffmpeg/ffmpeg.exe", "FFPROBE_PATH": "ffmpeg/ffprobe.exe", "WEBVIEW2_BROWSER_EXECUTABLE_FOLDER": "WebView2"} {
		if err = os.Setenv(key, filepath.Join(root, path)); err != nil {
			return err
		}
	}
	app := exec.Command(filepath.Join(root, "GB28181-Analyzer.exe"), os.Args[1:]...)
	return app.Run()
}

func main() {
	if err := launch(); err != nil {
		text, _ := syscall.UTF16PtrFromString(err.Error())
		title, _ := syscall.UTF16PtrFromString("GB28181 Analyzer 启动失败")
		syscall.NewLazyDLL("user32.dll").NewProc("MessageBoxW").Call(0, uintptr(unsafe.Pointer(text)), uintptr(unsafe.Pointer(title)), 16)
		os.Exit(1)
	}
}
