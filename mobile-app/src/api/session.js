import AsyncStorage from '@react-native-async-storage/async-storage';

const TOKEN_KEY = 'homeonq.token';
const EMAIL_KEY = 'homeonq.email';
let memory = {};

async function safeGet(key) {
  try {
    return await AsyncStorage.getItem(key);
  } catch (error) {
    return memory[key] || null;
  }
}

async function safeSet(key, value) {
  memory[key] = value;
  try {
    await AsyncStorage.setItem(key, value);
  } catch (error) {
    // 저장 실패(웹 사생활 모드 등)해도 이번 세션은 메모리로 유지한다.
  }
}

async function safeRemove(key) {
  delete memory[key];
  try {
    await AsyncStorage.removeItem(key);
  } catch (error) {
    // noop
  }
}

export const session = {
  async save(token, email) {
    await safeSet(TOKEN_KEY, token);
    if (email) await safeSet(EMAIL_KEY, email);
  },
  async token() {
    return safeGet(TOKEN_KEY);
  },
  async email() {
    return safeGet(EMAIL_KEY);
  },
  async clear() {
    await safeRemove(TOKEN_KEY);
    await safeRemove(EMAIL_KEY);
  },
};
