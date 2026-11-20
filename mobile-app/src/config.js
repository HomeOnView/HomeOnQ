const FALLBACK_API = 'http://localhost:8000';

// Expo는 EXPO_PUBLIC_* 환경변수를 빌드 시점에 주입한다.
export const API_BASE_URL = (process.env.EXPO_PUBLIC_API_URL || FALLBACK_API).replace(/\/+$/, '');
export const SOS_NUMBER = '01000000000';
export const APP_VERSION = '0.3.0';
