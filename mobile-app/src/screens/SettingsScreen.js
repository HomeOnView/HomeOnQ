import React from 'react';
import { View, Text, ScrollView, StyleSheet, TouchableOpacity } from 'react-native';
import { Card, SectionTitle } from '../components/Card';
import { colors } from '../theme';
import { API_BASE_URL, APP_VERSION } from '../config';

export default function SettingsScreen({ guardian, senior, health, demo, onLogout, onReset }) {
  const devices = (senior && senior.devices) || [];
  return (
    <ScrollView style={styles.scroll} contentContainerStyle={styles.container}>
      <Text style={styles.title}>설정</Text>

      <Card>
        <SectionTitle title="계정" />
        <Row label="보호자" value={guardian ? guardian.email : '데모 모드'} />
        <Row label="어르신" value={senior ? senior.display_name : '-'} />
        <Row label="응급 연락처" value={(senior && senior.emergency_contact) || '-'} />
      </Card>

      <Card>
        <SectionTitle title="카메라 · 기기" right={`${devices.length}대`} />
        {devices.length ? (
          devices.map((device) => (
            <Row
              key={device.device_id}
              label={device.device_id}
              sub={[device.health_status || device.status, device.last_seen_at ? new Date(device.last_seen_at).toLocaleTimeString('ko-KR') : null].filter(Boolean).join(' · ')}
              value={device.status === 'active' ? '정상' : device.status}
            />
          ))
        ) : (
          <Row label="등록된 카메라가 없습니다" value="-" />
        )}
      </Card>

      <Card>
        <SectionTitle title="서버 · 버전" />
        <Row label="API" value={API_BASE_URL} />
        <Row label="상태" value={demo ? '오프라인(데모)' : health ? `${health.status} · ${health.environment}` : '-'} />
        <Row label="버전" value={(health && health.version) || APP_VERSION} />
        <Row label="DB" value={(health && health.database) || '-'} />
      </Card>

      {!demo ? (
        <TouchableOpacity style={styles.ghostBtn} onPress={onReset}>
          <Text style={styles.ghostText}>데모 데이터 초기화</Text>
        </TouchableOpacity>
      ) : null}
      <TouchableOpacity style={styles.logoutBtn} onPress={onLogout}>
        <Text style={styles.logoutText}>로그아웃</Text>
      </TouchableOpacity>
      <Text style={styles.fineprint}>홈온큐(HOMEONQ) 시연용 앱 · v{APP_VERSION}</Text>
    </ScrollView>
  );
}

function Row({ label, value, sub }) {
  return (
    <View style={styles.row}>
      <View style={{ flex: 1 }}>
        <Text style={styles.rowLabel}>{label}</Text>
        {sub ? <Text style={styles.rowSub}>{sub}</Text> : null}
      </View>
      <Text style={styles.rowValue} numberOfLines={1}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  scroll: { flex: 1, backgroundColor: colors.bg },
  container: { padding: 14, paddingBottom: 30 },
  title: { fontSize: 17, fontWeight: '800', color: colors.navy, marginBottom: 10, paddingHorizontal: 4 },
  row: { flexDirection: 'row', alignItems: 'center', backgroundColor: '#fff', borderRadius: 14, borderWidth: 1, borderColor: colors.line, paddingHorizontal: 12, paddingVertical: 10, marginBottom: 6 },
  rowLabel: { fontSize: 12.5, color: '#47536B' },
  rowSub: { fontSize: 10.5, color: '#94A1B8', marginTop: 2 },
  rowValue: { fontSize: 12, fontWeight: '700', color: colors.navy, maxWidth: '55%', textAlign: 'right' },
  ghostBtn: { borderWidth: 1, borderColor: colors.line, backgroundColor: '#fff', borderRadius: 14, paddingVertical: 13, alignItems: 'center', marginTop: 4 },
  ghostText: { fontSize: 13, fontWeight: '700', color: colors.navy },
  logoutBtn: { paddingVertical: 14, alignItems: 'center', marginTop: 6 },
  logoutText: { fontSize: 13, fontWeight: '700', color: colors.red },
  fineprint: { fontSize: 10, color: '#8B98B1', textAlign: 'center', marginTop: 6 },
});
