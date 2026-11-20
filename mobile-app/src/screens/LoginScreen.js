import React, { useState } from 'react';
import { View, Text, TextInput, TouchableOpacity, StyleSheet, ScrollView, ActivityIndicator } from 'react-native';
import { colors } from '../theme';
import { API_BASE_URL } from '../config';

export default function LoginScreen({ demoConfig, onLogin, onDemo, busy, error }) {
  const credentials = (demoConfig && demoConfig.credentials) || {};
  const [email, setEmail] = useState(credentials.email || 'demo@homeonq.kr');
  const [password, setPassword] = useState(credentials.password || 'homeonq-demo-2026');

  return (
    <ScrollView contentContainerStyle={styles.container} keyboardShouldPersistTaps="handled">
      <View style={styles.hero}>
        <Text style={styles.heroTitle}>부모님의 하루를{'\n'}조용히 지켜보는 안심 리포트</Text>
        <Text style={styles.heroBody}>
          카메라가 관절 움직임을 분석해 낙상·장시간 무활동·배회를 살피고,{'\n'}보호자에게 따뜻한 말로 하루를 전합니다.
        </Text>
        <View style={styles.points}>
          <Text style={styles.point}>01  낙상이 의심되면 즉시 알림</Text>
          <Text style={styles.point}>02  매일 안심 점수와 리포트</Text>
          <Text style={styles.point}>03  어르신 정보 수정</Text>
        </View>
      </View>

      <View style={styles.card}>
        <Text style={styles.cardTitle}>보호자 로그인</Text>
        <Text style={styles.label}>이메일</Text>
        <TextInput
          style={styles.input}
          value={email}
          onChangeText={setEmail}
          autoCapitalize="none"
          keyboardType="email-address"
          placeholder="demo@homeonq.kr"
        />
        <Text style={styles.label}>비밀번호</Text>
        <TextInput style={styles.input} value={password} onChangeText={setPassword} secureTextEntry />
        {error ? <Text style={styles.error}>{error}</Text> : null}
        <TouchableOpacity style={styles.primaryBtn} onPress={() => onLogin(email.trim(), password)} disabled={busy}>
          {busy ? <ActivityIndicator color="#fff" /> : <Text style={styles.primaryText}>로그인</Text>}
        </TouchableOpacity>
        <TouchableOpacity style={styles.ghostBtn} onPress={onDemo}>
          <Text style={styles.ghostText}>서버 없이 데모로 보기</Text>
        </TouchableOpacity>
        <Text style={styles.hint}>API: {API_BASE_URL}</Text>
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { padding: 16, paddingBottom: 40, backgroundColor: colors.bg, flexGrow: 1 },
  hero: { backgroundColor: colors.navy, borderRadius: 24, padding: 20, marginBottom: 16 },
  heroTitle: { color: '#fff', fontSize: 21, fontWeight: '800', lineHeight: 30 },
  heroBody: { color: '#C7D3EA', fontSize: 12.5, lineHeight: 19, marginTop: 10 },
  points: { marginTop: 14 },
  point: { color: '#DFE7F5', fontSize: 12, marginTop: 6 },
  card: { backgroundColor: '#fff', borderRadius: 22, padding: 18 },
  cardTitle: { fontSize: 16, fontWeight: '800', color: colors.navy, marginBottom: 12 },
  label: { fontSize: 11.5, color: colors.muted, fontWeight: '600', marginBottom: 4, marginTop: 8 },
  input: {
    borderWidth: 1, borderColor: colors.line, borderRadius: 12, paddingHorizontal: 12, paddingVertical: 10,
    fontSize: 14, color: colors.ink, backgroundColor: '#F8FAFD',
  },
  primaryBtn: { backgroundColor: colors.navy, borderRadius: 14, paddingVertical: 14, alignItems: 'center', marginTop: 16 },
  primaryText: { color: '#fff', fontSize: 14, fontWeight: '800' },
  ghostBtn: { borderWidth: 1, borderColor: colors.line, borderRadius: 14, paddingVertical: 12, alignItems: 'center', marginTop: 8 },
  ghostText: { color: colors.navy, fontSize: 14, fontWeight: '700' },
  hint: { fontSize: 10.5, color: '#8B98B1', textAlign: 'center', marginTop: 12 },
  error: { color: colors.red, fontSize: 11.5, marginTop: 8 },
});
