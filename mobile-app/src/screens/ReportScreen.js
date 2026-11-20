import React, { useState } from 'react';
import { View, Text, ScrollView, StyleSheet, TouchableOpacity, Linking, RefreshControl } from 'react-native';
import ProfileCard from '../components/ProfileCard';
import ScoreCard from '../components/ScoreCard';
import { Card, SectionTitle } from '../components/Card';
import { colors } from '../theme';
import { SOS_NUMBER } from '../config';

const ICONS = {
  steps: '🚶', night_activity: '🌙', toilet: '🚻', bedroom: '🛏', inactivity: '⏳', wandering: '↔️',
};

function SummaryRows({ rows }) {
  if (!rows || !rows.length) {
    return <Text style={styles.empty}>오늘 집계된 활동이 아직 없습니다.</Text>;
  }
  return rows.map((row) => (
    <View key={row.key || row.label} style={styles.summaryRow}>
      <Text style={styles.summaryLabel}>
        {ICONS[row.key] || '•'}  {row.label}
      </Text>
      <View style={styles.summaryValueWrap}>
        <Text style={styles.summaryValue}>
          {Number(row.value).toLocaleString('ko-KR')}
          {row.unit || ''}
        </Text>
        {row.delta_percent != null ? (
          <Text style={[styles.delta, { color: row.delta_percent < 0 ? colors.red : colors.green }]}>
            {row.delta_percent > 0 ? '+' : ''}
            {row.delta_percent}%
          </Text>
        ) : null}
      </View>
    </View>
  ));
}

export default function ReportScreen({ senior, report, alerts, onEdit, onTestFall, onRefresh, refreshing, onAcknowledge }) {
  const [expanded, setExpanded] = useState(false);
  const narrative = (report && report.narrative) || '';
  const long = narrative.length > 220;

  return (
    <ScrollView
      style={styles.scroll}
      contentContainerStyle={styles.container}
      refreshControl={<RefreshControl refreshing={!!refreshing} onRefresh={onRefresh} tintColor={colors.navy} />}
    >
      <View style={styles.todayRow}>
        <Text style={styles.todayTitle}>오늘의 안심 리포트</Text>
        <Text style={styles.todayDate}>{report ? report.report_date : ''}</Text>
      </View>

      <ProfileCard senior={senior} onEdit={onEdit} />

      {alerts && alerts.length ? (
        <TouchableOpacity style={styles.alert} onPress={() => onAcknowledge(alerts[0])} activeOpacity={0.85}>
          <Text style={styles.alertTitle}>⚠️  확인하지 않은 알림</Text>
          <Text style={styles.alertBody}>
            {alerts[0].senior_name} · 낙상 의심 · {new Date(alerts[0].occurred_at).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' })}
          </Text>
          <Text style={styles.alertAction}>눌러서 확인 처리</Text>
        </TouchableOpacity>
      ) : null}

      <ScoreCard report={report} />

      <Card>
        <Text style={styles.eyebrow}>✦  AI 안심 리포트</Text>
        <Text style={styles.headline}>{(report && report.headline) || '아직 오늘의 리포트가 없습니다'}</Text>
        <Text style={styles.narrative} numberOfLines={expanded ? undefined : 6}>
          {narrative || '카메라 분석이 시작되면 이곳에 하루가 정리됩니다.'}
        </Text>
        {long ? (
          <Text style={styles.more} onPress={() => setExpanded(!expanded)}>
            {expanded ? '접기' : '전체 읽기'}
          </Text>
        ) : null}
      </Card>

      <Card>
        <SectionTitle title="주요 이벤트 요약" right={report ? report.report_date : ''} />
        <SummaryRows rows={report && report.summary ? report.summary.rows : []} />
      </Card>

      <View style={styles.actions}>
        <TouchableOpacity style={[styles.actionBtn, { backgroundColor: colors.red }]} onPress={() => Linking.openURL(`tel:${SOS_NUMBER}`)}>
          <Text style={styles.actionText}>SOS 안심전화</Text>
        </TouchableOpacity>
        <TouchableOpacity style={[styles.actionBtn, { backgroundColor: '#EEF2FA' }]} onPress={onTestFall}>
          <Text style={[styles.actionText, { color: colors.navy }]}>낙상 테스트</Text>
        </TouchableOpacity>
      </View>
      <Text style={styles.fineprint}>홈온큐는 의료 진단을 대신하지 않습니다. 리포트는 관절 좌표 분석 기반 참고 자료입니다.</Text>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  scroll: { flex: 1, backgroundColor: colors.bg },
  container: { padding: 14, paddingBottom: 30 },
  todayRow: { flexDirection: 'row', alignItems: 'baseline', justifyContent: 'space-between', paddingHorizontal: 4, marginBottom: 10 },
  todayTitle: { fontSize: 17, fontWeight: '800', color: colors.navy },
  todayDate: { fontSize: 12, color: colors.muted },
  alert: { backgroundColor: '#FFF6F5', borderRadius: 16, borderWidth: 1, borderColor: '#F3CDC8', padding: 14, marginBottom: 12 },
  alertTitle: { fontSize: 13, fontWeight: '800', color: colors.red },
  alertBody: { fontSize: 12, color: '#6B3A35', marginTop: 4 },
  alertAction: { fontSize: 11, color: colors.red, fontWeight: '700', marginTop: 8 },
  eyebrow: { fontSize: 11, fontWeight: '800', color: colors.navy2, marginBottom: 6 },
  headline: { fontSize: 15.5, fontWeight: '800', color: colors.navy, lineHeight: 22, marginBottom: 8 },
  narrative: { fontSize: 12.8, lineHeight: 21, color: '#3A475F' },
  more: { fontSize: 12, color: colors.navy2, fontWeight: '700', marginTop: 8, textDecorationLine: 'underline' },
  summaryRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: '#F1F4FA' },
  summaryLabel: { fontSize: 12.5, color: '#47536B' },
  summaryValueWrap: { flexDirection: 'row', alignItems: 'center' },
  summaryValue: { fontSize: 13, fontWeight: '800', color: colors.navy },
  delta: { fontSize: 10.5, fontWeight: '700', marginLeft: 6 },
  empty: { fontSize: 12, color: colors.muted },
  actions: { flexDirection: 'row', justifyContent: 'space-between', marginTop: 2 },
  actionBtn: { flex: 0.48, paddingVertical: 13, borderRadius: 14, alignItems: 'center' },
  actionText: { color: '#fff', fontSize: 13, fontWeight: '800' },
  fineprint: { fontSize: 10, color: '#8B98B1', textAlign: 'center', marginTop: 12, lineHeight: 15 },
});
