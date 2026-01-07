import type { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
  appId: 'com.monitor.page',
  appName: 'Monitor Page',
  webDir: 'build',
  server: {
    // 개발 시 로컬 서버 연결 (선택)
    // url: 'http://192.168.x.x:5174',
    // cleartext: true
  },
  android: {
    allowMixedContent: true
  }
};

export default config;
