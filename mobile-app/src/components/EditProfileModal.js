import React, { useState } from 'react';
import { View, Text, Modal, StyleSheet, TextInput, TouchableOpacity, ScrollView, ActivityIndicator } from 'react-native';
import { colors } from '../theme';

export default function EditProfileModal({ visible, senior, onClose, onSave, saving }) {
  const [form, setForm] = useState({});
  const value = (key, fallback) => (form[key] !== undefined ? form[key] : fallback);

  const set = (key) => (text) => setForm((prev) => ({ ...prev, [key]: text }));

  const submit = () => {
    const body = {};
    const name = value('display_name', senior.display_name || '').trim();
    if (name) body.display_name = name;
    if (value('birth_date', senior.birth_date || '')) body.birth_date = value('birth_date', senior.birth_date || '');
    if (value('gender', senior.gender || '여성')) body.gender = value('gender', senior.gender || '여성');
    const height = value('height_cm', senior.height_cm ? String(senior.height_cm) : '');
    if (height) body.height_cm = Number(height);
    const weight = value('weight_kg', senior.weight_kg ? String(senior.weight_kg) : '');
    if (weight) body.weight_kg = Number(weight);
    const conditions = value('medical_conditions', (senior.medical_conditions || []).join(', '));
    body.medical_conditions = conditions
      ? conditions.split(',').map((item) => item.trim()).filter(Boolean)
      : [];
    body.emergency_contact = value('emergency_contact', senior.emergency_contact || '') || null;
    body.photo_url = value('photo_url', senior.photo_url || '') || null;
    body.memo = value('memo', senior.memo || '') || null;
    onSave(body);
  };

  if (!senior) return null;

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.backdrop}>
        <View style={styles.sheet}>
          <ScrollView keyboardShouldPersistTaps="handled">
            <Text style={styles.title}>어르신 프로필 수정</Text>
            <Field label="성함" value={value('display_name', senior.display_name || '')} onChangeText={set('display_name')} />
            <Field label="생년월일 (YYYY-MM-DD)" value={value('birth_date', senior.birth_date || '')} onChangeText={set('birth_date')} />
            <Field label="성별" value={value('gender', senior.gender || '여성')} onChangeText={set('gender')} />
            <Field label="키 (cm)" value={value('height_cm', senior.height_cm ? String(senior.height_cm) : '')} onChangeText={set('height_cm')} keyboardType="numeric" />
            <Field label="체중 (kg)" value={value('weight_kg', senior.weight_kg ? String(senior.weight_kg) : '')} onChangeText={set('weight_kg')} keyboardType="numeric" />
            <Field label="병력/질환 (쉼표로 구분)" value={value('medical_conditions', (senior.medical_conditions || []).join(', '))} onChangeText={set('medical_conditions')} />
            <Field label="응급 연락처" value={value('emergency_contact', senior.emergency_contact || '')} onChangeText={set('emergency_contact')} />
            <Field label="프로필 사진 URL" value={value('photo_url', senior.photo_url || '')} onChangeText={set('photo_url')} autoCapitalize="none" />
            <Field label="메모" value={value('memo', senior.memo || '')} onChangeText={set('memo')} multiline />
            <View style={styles.actions}>
              <TouchableOpacity style={styles.ghost} onPress={onClose}>
                <Text style={styles.ghostText}>취소</Text>
              </TouchableOpacity>
              <TouchableOpacity style={styles.primary} onPress={submit} disabled={saving}>
                {saving ? <ActivityIndicator color="#fff" /> : <Text style={styles.primaryText}>저장하기</Text>}
              </TouchableOpacity>
            </View>
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}

function Field({ label, ...props }) {
  return (
    <View style={{ marginTop: 10 }}>
      <Text style={styles.label}>{label}</Text>
      <TextInput style={[styles.input, props.multiline && { height: 64, textAlignVertical: 'top' }]} placeholderTextColor="#9AA8C0" {...props} />
    </View>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: 'rgba(6,14,32,0.62)', justifyContent: 'flex-end' },
  sheet: { backgroundColor: '#fff', borderTopLeftRadius: 24, borderTopRightRadius: 24, padding: 20, maxHeight: '90%' },
  title: { fontSize: 16.5, fontWeight: '800', color: colors.navy, marginBottom: 4 },
  label: { fontSize: 11.5, color: colors.muted, fontWeight: '600', marginBottom: 4 },
  input: { borderWidth: 1, borderColor: colors.line, borderRadius: 12, paddingHorizontal: 12, paddingVertical: 9, fontSize: 13.5, color: colors.ink, backgroundColor: '#F8FAFD' },
  actions: { flexDirection: 'row', marginTop: 18, marginBottom: 8 },
  ghost: { flex: 1, borderWidth: 1, borderColor: colors.line, borderRadius: 12, paddingVertical: 13, alignItems: 'center', marginRight: 8 },
  ghostText: { fontSize: 13, fontWeight: '700', color: colors.navy },
  primary: { flex: 1, backgroundColor: colors.navy, borderRadius: 12, paddingVertical: 13, alignItems: 'center' },
  primaryText: { fontSize: 13, fontWeight: '800', color: '#fff' },
});
