import React, { useMemo, useState } from 'react';
import { View, Text, ScrollView, StyleSheet, TouchableOpacity, RefreshControl, Modal } from 'react-native';
import { colors } from '../theme';

const STATUS_LABEL = {
  ANALYZED: '분석 완료', RECEIVED: '수신됨', SUSPECTED: '의심', CONFIRMED: '확인됨',
  DISMISSED: '오탐', SENT: '전송됨', PENDING: '대기',
};
const RISK_LABEL = { HIGH: '높음', MEDIUM: '보통', LOW: '낮음' };
const ICON = {
  WALKING: '🚶', NIGHT_ACTIVITY: '🌙', TOILET_VISIT: '🚻', BEDROOM_STAY: '🛏',
  INACTIVE: '⏳', WANDERING: '↔️',
};

function fmt(iso) {
  if (!iso) return '-';
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  const today = new Date();
  const same = d.toDateString() === today.toDateString();
  const time = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
  return `${same ? '오늘' : `${d.getMonth() + 1}월 ${d.getDate()}일`} ${time}`;
}

export default function EventsScreen({ events, onRefresh, refreshing, onUpdateFall }) {
  const [filter, setFilter] = useState('all');
  const [selected, setSelected] = useState(null);
  const visible = useMemo(() => events.filter((e) => filter === 'all' || e.kind === filter), [events, filter]);

  return (
    <View style={styles.wrap}>
      <View style={styles.header}>
        <Text style={styles.title}>최근 이벤트</Text>
        <View style={styles.segment}>
          {[['all', '전체'], ['fall', '낙상'], ['behavior', '행동']].map(([key, label]) => (
            <TouchableOpacity key={key} style={[styles.segmentBtn, filter === key && styles.segmentActive]} onPress={() => setFilter(key)}>
              <Text style={[styles.segmentText, filter === key && styles.segmentTextActive]}>{label}</Text>
            </TouchableOpacity>
          ))}
        </View>
      </View>

      <ScrollView
        contentContainerStyle={styles.list}
        refreshControl={<RefreshControl refreshing={!!refreshing} onRefresh={onRefresh} tintColor={colors.navy} />}
      >
        {visible.length === 0 ? (
          <Text style={styles.empty}>이 기간에는 특별한 이벤트가 없습니다.{'\n'}분석 테스트에서 낙상을 실행해 보세요.</Text>
        ) : (
          visible.map((event, index) => {
            const isFall = event.kind === 'fall';
            return (
              <TouchableOpacity key={`${event.id || event.event_id}-${index}`} style={styles.item} onPress={() => setSelected(event)} activeOpacity={0.8}>
                <View style={[styles.icon, { backgroundColor: isFall ? colors.redSoft : '#EEF2FA' }]}>
                  <Text style={{ fontSize: 15 }}>{isFall ? '⚠️' : ICON[event.activity_type] || '•'}</Text>
                </View>
                <View style={styles.body}>
                  <View style={styles.titleRow}>
                    <Text style={styles.itemTitle}>{event.title || event.event_type}</Text>
                    <Text style={styles.pill}>{isFall ? STATUS_LABEL[event.status] || '의심' : STATUS_LABEL[event.status] || ''}</Text>
                    {event.is_test ? <Text style={styles.pill}>테스트</Text> : null}
                  </View>
                  <Text style={styles.desc} numberOfLines={2}>{event.detail || ''}</Text>
                  <Text style={styles.meta}>
                    {fmt(event.occurred_at)}
                    {event.confidence != null ? `  신뢰도 ${Math.round(event.confidence * 100)}%` : ''}
                    {event.value != null ? `  ${Number(event.value).toLocaleString('ko-KR')}${event.unit || ''}` : ''}
                  </Text>
                </View>
              </TouchableOpacity>
            );
          })
        )}
      </ScrollView>

      <Modal visible={!!selected} transparent animationType="slide" onRequestClose={() => setSelected(null)}>
        <View style={styles.modalBackdrop}>
          <View style={styles.sheet}>
            <Text style={styles.sheetTitle}>{selected ? selected.title || selected.event_type : ''}</Text>
            <Text style={styles.sheetSub}>{selected && selected.kind === 'fall' ? '낙상 의심 이벤트' : '일일 활동 이벤트'}</Text>
            <View style={styles.detailRow}>
              <Text style={styles.detailLabel}>발생 시각</Text>
              <Text style={styles.detailValue}>{selected ? fmt(selected.occurred_at) : ''}</Text>
            </View>
            <View style={styles.detailRow}>
              <Text style={styles.detailLabel}>상태</Text>
              <Text style={styles.detailValue}>{selected ? STATUS_LABEL[selected.status] || selected.status || '-' : ''}</Text>
            </View>
            {selected && selected.risk_level ? (
              <View style={styles.detailRow}>
                <Text style={styles.detailLabel}>위험도</Text>
                <Text style={styles.detailValue}>{RISK_LABEL[selected.risk_level] || selected.risk_level}</Text>
              </View>
            ) : null}
            <Text style={styles.reason}>{selected ? selected.detail || '상세 설명이 없습니다.' : ''}</Text>
            {selected && selected.kind === 'fall' ? (
              <View style={styles.sheetActions}>
                <TouchableOpacity style={styles.ghostBtn} onPress={() => setSelected(null)}>
                  <Text style={styles.ghostText}>닫기</Text>
                </TouchableOpacity>
                <TouchableOpacity style={styles.ghostBtn} onPress={() => { onUpdateFall(selected, 'DISMISSED'); setSelected(null); }}>
                  <Text style={styles.ghostText}>오탐 처리</Text>
                </TouchableOpacity>
                <TouchableOpacity style={styles.primaryBtn} onPress={() => { onUpdateFall(selected, 'CONFIRMED'); setSelected(null); }}>
                  <Text style={styles.primaryText}>확인 완료</Text>
                </TouchableOpacity>
              </View>
            ) : (
              <TouchableOpacity style={[styles.primaryBtn, { marginTop: 16 }]} onPress={() => setSelected(null)}>
                <Text style={styles.primaryText}>닫기</Text>
              </TouchableOpacity>
            )}
          </View>
        </View>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: colors.bg },
  header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 16, paddingTop: 12 },
  title: { fontSize: 17, fontWeight: '800', color: colors.navy },
  segment: { flexDirection: 'row', backgroundColor: '#E6ECF6', borderRadius: 10, padding: 3 },
  segmentBtn: { paddingHorizontal: 10, paddingVertical: 5, borderRadius: 8 },
  segmentActive: { backgroundColor: '#fff' },
  segmentText: { fontSize: 11.5, fontWeight: '700', color: '#5B6884' },
  segmentTextActive: { color: colors.navy },
  list: { padding: 14, paddingBottom: 30 },
  item: { flexDirection: 'row', backgroundColor: '#fff', borderRadius: 16, padding: 13, marginBottom: 8, borderWidth: 1, borderColor: colors.line },
  icon: { width: 34, height: 34, borderRadius: 11, alignItems: 'center', justifyContent: 'center', marginRight: 10 },
  body: { flex: 1 },
  titleRow: { flexDirection: 'row', alignItems: 'center' },
  itemTitle: { fontSize: 13, fontWeight: '800', color: colors.navy, marginRight: 6 },
  pill: { fontSize: 9.5, color: '#5B6884', backgroundColor: '#F0F3F9', borderRadius: 5, paddingHorizontal: 5, paddingVertical: 1, marginRight: 4 },
  desc: { fontSize: 11.5, color: colors.muted, marginTop: 3, lineHeight: 16 },
  meta: { fontSize: 10.5, color: '#94A1B8', marginTop: 5 },
  empty: { textAlign: 'center', color: '#8B98B1', fontSize: 12.5, lineHeight: 20, marginTop: 60 },
  modalBackdrop: { flex: 1, backgroundColor: 'rgba(6,14,32,0.62)', justifyContent: 'flex-end' },
  sheet: { backgroundColor: '#fff', borderTopLeftRadius: 24, borderTopRightRadius: 24, padding: 20 },
  sheetTitle: { fontSize: 16.5, fontWeight: '800', color: colors.navy },
  sheetSub: { fontSize: 11.5, color: colors.muted, marginTop: 3, marginBottom: 10 },
  detailRow: { flexDirection: 'row', justifyContent: 'space-between', paddingVertical: 7, borderBottomWidth: 1, borderBottomColor: '#F1F4FA' },
  detailLabel: { fontSize: 12, color: colors.muted },
  detailValue: { fontSize: 12.5, fontWeight: '700', color: colors.navy },
  reason: { fontSize: 12, color: '#3A475F', lineHeight: 19, backgroundColor: '#F8FAFD', borderRadius: 12, padding: 12, marginTop: 12 },
  sheetActions: { flexDirection: 'row', marginTop: 16 },
  ghostBtn: { flex: 1, borderWidth: 1, borderColor: colors.line, borderRadius: 12, paddingVertical: 12, alignItems: 'center', marginRight: 8 },
  ghostText: { fontSize: 12.5, fontWeight: '700', color: colors.navy },
  primaryBtn: { flex: 1, backgroundColor: colors.navy, borderRadius: 12, paddingVertical: 12, alignItems: 'center' },
  primaryText: { fontSize: 12.5, fontWeight: '800', color: '#fff' },
});
