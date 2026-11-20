import React from 'react';
import { View, Text, Modal, StyleSheet, TouchableOpacity, Linking } from 'react-native';
import { colors } from '../theme';
import { SOS_NUMBER } from '../config';

export default function FallAlertModal({ alert, onClose, onAcknowledge }) {
  if (!alert) return null;
  const time = new Date(alert.occurred_at);
  const timeText = isNaN(time) ? '-' : `${time.getMonth() + 1}월 ${time.getDate()}일 ${String(time.getHours()).padStart(2, '0')}:${String(time.getMinutes()).padStart(2, '0')}`;
  return (
    <Modal visible transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.backdrop}>
        <View style={styles.sheet}>
          <View style={styles.visual}>
            <Text style={{ fontSize: 32 }}>⚠️</Text>
          </View>
          {alert.is_test ? <Text style={styles.testChip}>테스트 알림</Text> : null}
          <Text style={styles.title}>낙상 비상 상황 발생</Text>
          <Text style={styles.name}>{alert.senior_name}</Text>
          <View style={styles.detail}>
            <Text style={styles.detailTime}>{timeText} · 신뢰도 {Math.round((alert.confidence || 0) * 100)}%</Text>
            <Text style={styles.detailBody}>{alert.reasoning || '카메라 관절 분석에서 낙상이 의심되는 자세 변화가 감지되었습니다.'}</Text>
          </View>
          <TouchableOpacity style={styles.sos} onPress={() => Linking.openURL(`tel:${SOS_NUMBER}`)}>
            <Text style={styles.sosText}>즉시 SOS 긴급 전화</Text>
          </TouchableOpacity>
          <TouchableOpacity style={styles.ack} onPress={() => onAcknowledge(alert)}>
            <Text style={styles.ackText}>확인했습니다</Text>
          </TouchableOpacity>
          <TouchableOpacity style={styles.close} onPress={onClose}>
            <Text style={styles.closeText}>나중에</Text>
          </TouchableOpacity>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: 'rgba(6,14,32,0.7)', justifyContent: 'center', padding: 20 },
  sheet: { backgroundColor: '#fff', borderRadius: 24, padding: 20, alignItems: 'center' },
  visual: { width: 84, height: 84, borderRadius: 42, backgroundColor: colors.red, alignItems: 'center', justifyContent: 'center', marginBottom: 12 },
  testChip: { fontSize: 10, fontWeight: '800', color: '#7A5310', backgroundColor: '#FFF3D6', borderRadius: 5, paddingHorizontal: 6, paddingVertical: 2, marginBottom: 6 },
  title: { fontSize: 19, fontWeight: '800', color: colors.red },
  name: { fontSize: 13, fontWeight: '800', color: colors.navy, marginTop: 2, marginBottom: 10 },
  detail: { backgroundColor: '#FFF6F5', borderWidth: 1, borderColor: '#F6D6D2', borderRadius: 14, padding: 12, width: '100%' },
  detailTime: { fontSize: 12, fontWeight: '800', color: '#8F1D14', marginBottom: 4 },
  detailBody: { fontSize: 12, color: '#6B3A35', lineHeight: 18 },
  sos: { backgroundColor: colors.red, borderRadius: 14, paddingVertical: 13, width: '100%', alignItems: 'center', marginTop: 14 },
  sosText: { color: '#fff', fontSize: 13, fontWeight: '800' },
  ack: { backgroundColor: colors.navy, borderRadius: 14, paddingVertical: 13, width: '100%', alignItems: 'center', marginTop: 8 },
  ackText: { color: '#fff', fontSize: 13, fontWeight: '800' },
  close: { paddingVertical: 12 },
  closeText: { fontSize: 12.5, color: colors.muted },
});
