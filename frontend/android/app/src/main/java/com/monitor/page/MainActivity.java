package com.monitor.page;

import android.content.Intent;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    // WebView 준비 전 수신된 Share Intent URL 저장
    private String pendingShareUrl = null;
    // WebView 준비 여부
    private boolean isWebViewReady = false;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        handleShareIntent(getIntent());
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        handleShareIntent(intent);
    }

    /**
     * Share Intent 처리
     * 다른 앱에서 URL을 공유하면 이 메서드가 호출됨
     */
    private void handleShareIntent(Intent intent) {
        String action = intent.getAction();
        String type = intent.getType();

        if (Intent.ACTION_SEND.equals(action) && type != null) {
            if ("text/plain".equals(type)) {
                String sharedText = intent.getStringExtra(Intent.EXTRA_TEXT);
                if (sharedText != null && !sharedText.isEmpty()) {
                    if (isWebViewReady) {
                        sendToWebView(sharedText);
                    } else {
                        // WebView가 아직 준비되지 않았으면 저장해두고 나중에 전달
                        pendingShareUrl = sharedText;
                        // 약간의 지연 후 재시도 (WebView 초기화 대기)
                        new Handler(Looper.getMainLooper()).postDelayed(() -> {
                            if (pendingShareUrl != null) {
                                sendToWebView(pendingShareUrl);
                                pendingShareUrl = null;
                            }
                        }, 1500);
                    }
                }
            }
        }
    }

    /**
     * JavaScript로 공유된 URL 전달
     */
    private void sendToWebView(String sharedText) {
        if (getBridge() != null && getBridge().getWebView() != null) {
            isWebViewReady = true;
            // 특수문자 이스케이프
            String escapedText = sharedText
                .replace("\\", "\\\\")
                .replace("'", "\\'")
                .replace("\n", "\\n")
                .replace("\r", "\\r");

            String js = "window.handleNativeShare && window.handleNativeShare('" + escapedText + "')";
            getBridge().getWebView().evaluateJavascript(js, null);
        }
    }

    @Override
    public void onStart() {
        super.onStart();
        // WebView가 준비되면 대기 중인 공유 URL 처리
        new Handler(Looper.getMainLooper()).postDelayed(() -> {
            isWebViewReady = true;
            if (pendingShareUrl != null) {
                sendToWebView(pendingShareUrl);
                pendingShareUrl = null;
            }
        }, 2000);
    }
}
