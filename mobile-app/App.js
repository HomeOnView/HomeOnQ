import React, { useCallback, useEffect, useRef, useState } from 'react';
import { SafeAreaView, View, Text, StyleSheet, TouchableOpacity, StatusBar, ActivityIndicator, Alert } from 'react-native';
import { api, isNetworkError } from './src/api/client';
import { session } from './src/api/session';
import { demoSenior, demoReport, demoEvents, demoAlerts } from './src/api/demoData';
import LoginScreen from './src/screens/LoginScreen';
import ReportScreen from './src/screens/ReportScreen';
import EventsScreen from './src/screens/EventsScreen';
import SettingsScreen from './src/screens/SettingsScreen';
import FallAlertModal from './src/components/FallAlertModal';
import EditProfileModal from './src/components/EditProfileModal';
import { colors } from './src/theme';

export default function App() {
  const [booting, setBooting] = useState(true);
  const [token, setToken] = useState(null);
  const [guardian, setGuardian] = useState(null);
  const [demo, setDemo] = useState(false);
  const [demoConfig, setDemoConfig] = useState(null);
  const [senior, setSenior] = useState(null);
  const [report, setReport] = useState(null);
  const [events, setEvents] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [health, setHealth] = useState(null);
  const [tab, setTab] = useState('report');
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [loginError, setLoginError] = useState('');
  const [alert, setAlert] = useState(null);
  const [editVisible, setEditVisible] = useState(false);
  const [savingProfile, setSavingProfile] = useState(false);
  const pollRef = useRef(null);
  const lastAlertRef = useRef(null);

  const loadAll = useCallback(async (authToken) => {
    const seniors = await api.seniors(authToken);
    if (!seniors.items || !seniors.items.length) {
      throw new Error('연결된 어르신이 없습니다. 서버에서 데모 데이터를 먼저 생성하세요.');
    }
    const target = seniors.items[0];
    setSenior(target);
    const [reportData, eventData, alertData, healthData] = await Promise.all([
      api.latestReport(authToken, target.id).catch(() => null),
      api.events(authToken, target.id).catch(() => ({ items: [] })),
      api.alerts(authToken).catch(() => ({ items: [] })),
      api.health().catch(() => null),
    ]);
    setReport(reportData);
    setEvents((eventData && eventData.items) || []);
    setAlerts((alertData && alertData.items) || []);
    setHealth(healthData);
    return target;
  }, []);

  const startPolling = useCallback((authToken) => {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const data = await api.alerts(authToken);
        const items = (data && data.items) || [];
        setAlerts(items);
        const newest = items[0];
        if (newest && newest.notification_id !== lastAlertRef.current) {
          lastAlertRef.current = newest.notification_id;
          setAlert(newest);
        }
      } catch (error) {
        // 폴링 실패는 조용히 무시하고 다음 주기에 재시도한다.
      }
    }, 20000);
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const config = await api.demoConfig();
        setDemoConfig(config);
      } catch (error) {
        setDemoConfig(null);
      }
      const saved = await session.token();
      if (saved) {
        try {
          const me = await api.me(saved);
          const target = await loadAll(saved);
          setToken(saved);
          setGuardian(me);
          if (target) startPolling(saved);
        } catch (error) {
          await session.clear();
        }
      }
      setBooting(false);
    })();
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [loadAll, startPolling]);

  const handleLogin = async (email, password) => {
    setBusy(true);
    setLoginError('');
    try {
      const tokens = await api.login(email, password);
      await session.save(tokens.access_token, email);
      const me = await api.me(tokens.access_token).catch(() => ({ email }));
      const target = await loadAll(tokens.access_token);
      setToken(tokens.access_token);
      setGuardian(me);
      setDemo(false);
      setSenior(target);
      if (target) startPolling(tokens.access_token);
    } catch (error) {
      if (isNetworkError(error)) {
        enterDemo('서버에 연결할 수 없어 데모 데이터로 시작합니다.');
      } else {
        setLoginError(error.message || '로그인에 실패했습니다.');
      }
    } finally {
      setBusy(false);
    }
  };

  const enterDemo = (message) => {
    setDemo(true);
    setToken(null);
    setGuardian({ email: 'demo@homeonq.kr' });
    setSenior(demoSenior);
    setReport(demoReport);
    setEvents(demoEvents);
    setAlerts(demoAlerts);
    setLoginError('');
    if (message) Alert.alert('데모 모드', message);
  };

  const refresh = async () => {
    if (demo || !token) return;
    setRefreshing(true);
    try {
      await loadAll(token);
    } catch (error) {
      Alert.alert('새로고침 실패', error.message || '잠시 후 다시 시도해 주세요.');
    } finally {
      setRefreshing(false);
    }
  };

  const handleTestFall = async () => {
    if (demo) {
      Alert.alert('데모 모드', '서버 연결 후 사용할 수 있습니다.');
      return;
    }
    try {
      await api.testFall(token, senior.id);
      await loadAll(token);
      const data = await api.alerts(token);
      const newest = (data && data.items && data.items[0]) || null;
      setAlerts((data && data.items) || []);
      if (newest) {
        lastAlertRef.current = newest.notification_id;
        setAlert(newest);
      }
    } catch (error) {
      Alert.alert('실패', error.message || '테스트 알림을 만들지 못했습니다.');
    }
  };

  const acknowledge = async (target) => {
    if (demo) {
      setAlert(null);
      return;
    }
    try {
      await api.acknowledge(token, target.notification_id);
      setAlert(null);
      await loadAll(token);
    } catch (error) {
      Alert.alert('실패', error.message || '확인 처리에 실패했습니다.');
    }
  };

  const saveProfile = async (body) => {
    setSavingProfile(true);
    try {
      if (demo) {
        setSenior({ ...senior, ...body });
      } else {
        const updated = await api.patchSenior(token, senior.id, body);
        setSenior(updated);
        await loadAll(token);
      }
      setEditVisible(false);
    } catch (error) {
      Alert.alert('저장 실패', error.message || '프로필을 저장하지 못했습니다.');
    } finally {
      setSavingProfile(false);
    }
  };

  const updateFallStatus = async (event, status) => {
    if (demo) return;
    try {
      await api.patchFall(token, senior.id, event.event_id, status);
      await loadAll(token);
    } catch (error) {
      Alert.alert('실패', error.message || '상태를 바꾸지 못했습니다.');
    }
  };

  const logout = async () => {
    if (pollRef.current) clearInterval(pollRef.current);
    await session.clear();
    setToken(null);
    setGuardian(null);
    setDemo(false);
    setSenior(null);
    setReport(null);
    setEvents([]);
    setAlerts([]);
    setTab('report');
  };

  const resetDemoData = async () => {
    if (demo || !token) return;
    try {
      await api.reset(token);
      await loadAll(token);
      Alert.alert('완료', '데모 데이터를 초기화했습니다.');
    } catch (error) {
      Alert.alert('실패', error.message || '초기화에 실패했습니다.');
    }
  };

  if (booting) {
    return (
      <SafeAreaView style={[styles.flex, styles.center]}>
        <StatusBar barStyle="light-content" />
        <ActivityIndicator color={colors.navy} size="large" />
        <Text style={styles.loading}>홈온큐를 준비하고 있습니다…</Text>
      </SafeAreaView>
    );
  }

  if (!token && !demo) {
    return (
      <SafeAreaView style={styles.flex}>
        <StatusBar barStyle="light-content" />
        <View style={styles.header}>
          <View>
            <Text style={styles.brand}>홈온큐</Text>
            <Text style={styles.brandSub}>보호자 안심 리포트</Text>
          </View>
        </View>
        <LoginScreen demoConfig={demoConfig} onLogin={handleLogin} onDemo={() => enterDemo()} busy={busy} error={loginError} />
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.flex}>
      <StatusBar barStyle="light-content" />
      <View style={styles.header}>
        <View style={{ flex: 1 }}>
          <Text style={styles.brand}>홈온큐</Text>
          <Text style={styles.brandSub}>{demo ? '데모 모드' : '보호자 안심 리포트'}</Text>
        </View>
        <TouchableOpacity style={styles.testBtn} onPress={handleTestFall}>
          <Text style={styles.testBtnText}>낙상 테스트</Text>
        </TouchableOpacity>
      </View>

      <View style={styles.flex}>
        {tab === 'report' ? (
          <ReportScreen
            senior={senior}
            report={report}
            alerts={alerts}
            onEdit={() => setEditVisible(true)}
            onTestFall={handleTestFall}
            onRefresh={refresh}
            refreshing={refreshing}
            onAcknowledge={acknowledge}
          />
        ) : null}
        {tab === 'events' ? (
          <EventsScreen events={events} onRefresh={refresh} refreshing={refreshing} onUpdateFall={updateFallStatus} />
        ) : null}
        {tab === 'settings' ? (
          <SettingsScreen guardian={guardian} senior={senior} health={health} demo={demo} onLogout={logout} onReset={resetDemoData} />
        ) : null}
      </View>

      <View style={styles.tabbar}>
        {[['report', '리포트', '⌂'], ['events', '이벤트', '⚠'], ['settings', '설정', '⚙']].map(([key, label, icon]) => (
          <TouchableOpacity key={key} style={styles.tab} onPress={() => setTab(key)}>
            <Text style={[styles.tabIcon, tab === key && styles.tabActive]}>{icon}</Text>
            <Text style={[styles.tabLabel, tab === key && styles.tabActive]}>{label}</Text>
          </TouchableOpacity>
        ))}
      </View>

      <FallAlertModal alert={alert} onClose={() => setAlert(null)} onAcknowledge={acknowledge} />
      <EditProfileModal
        visible={editVisible}
        senior={senior}
        saving={savingProfile}
        onClose={() => setEditVisible(false)}
        onSave={saveProfile}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1, backgroundColor: colors.bg },
  center: { alignItems: 'center', justifyContent: 'center' },
  loading: { marginTop: 12, fontSize: 12.5, color: colors.muted },
  header: {
    flexDirection: 'row', alignItems: 'center', backgroundColor: colors.navy,
    paddingHorizontal: 16, paddingVertical: 12,
  },
  brand: { color: '#fff', fontSize: 16, fontWeight: '800' },
  brandSub: { color: '#A9BBDD', fontSize: 11, marginTop: 1 },
  testBtn: { backgroundColor: 'rgba(255,255,255,0.12)', borderWidth: 1, borderColor: 'rgba(255,255,255,0.2)', borderRadius: 9, paddingHorizontal: 10, paddingVertical: 6 },
  testBtnText: { color: '#fff', fontSize: 11, fontWeight: '700' },
  tabbar: {
    flexDirection: 'row', backgroundColor: '#fff', borderTopWidth: 1, borderTopColor: '#E3E9F3',
    paddingVertical: 8, paddingBottom: 12,
  },
  tab: { flex: 1, alignItems: 'center' },
  tabIcon: { fontSize: 18, color: '#8794AD' },
  tabLabel: { fontSize: 10, fontWeight: '700', color: '#8794AD', marginTop: 2 },
  tabActive: { color: colors.navy },
});
