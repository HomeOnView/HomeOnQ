import React from 'react';
import { View, Text, Image, StyleSheet } from 'react-native';
import { colors } from '../theme';

function Avatar({ senior }) {
  if (senior.photo_url) {
    return <Image source={{ uri: senior.photo_url }} style={styles.avatar} />;
  }
  const initial = (senior.display_name || '?').replace(/ .*/, '').slice(0, 1);
  return (
    <View style={styles.avatarFallback}>
      <Text style={styles.avatarText}>{initial}</Text>
    </View>
  );
}

export default function ProfileCard({ senior, onEdit }) {
  if (!senior) return null;
  const detail = [];
  if (senior.age) detail.push(`${senior.age}세`);
  else if (senior.birth_date) detail.push(`${new Date(senior.birth_date).getFullYear()}년생`);
  if (senior.gender) detail.push(senior.gender);
  if (senior.height_cm) detail.push(`${senior.height_cm}cm`);
  if (senior.weight_kg) detail.push(`${senior.weight_kg}kg`);

  return (
    <View style={styles.card}>
      <Avatar senior={senior} />
      <View style={styles.info}>
        <View style={styles.row}>
          <Text style={styles.name}>{senior.display_name}</Text>
          {onEdit ? (
            <Text style={styles.edit} onPress={onEdit}>
              수정
            </Text>
          ) : null}
        </View>
        <Text style={styles.detail}>{detail.join('  |  ')}</Text>
        <View style={styles.tags}>
          {(senior.medical_conditions || []).map((tag) => (
            <View key={tag} style={styles.tag}>
              <Text style={styles.tagText}>{tag}</Text>
            </View>
          ))}
        </View>
        {senior.memo ? <Text style={styles.memo}>{senior.memo}</Text> : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: { flexDirection: 'row', backgroundColor: colors.card, borderRadius: 20, padding: 16, marginBottom: 12 },
  avatar: { width: 58, height: 58, borderRadius: 18, backgroundColor: '#E8EEF8' },
  avatarFallback: {
    width: 58, height: 58, borderRadius: 18, alignItems: 'center', justifyContent: 'center',
    backgroundColor: '#DFE7F5',
  },
  avatarText: { fontSize: 20, fontWeight: '800', color: colors.navy },
  info: { flex: 1, marginLeft: 12 },
  row: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  name: { fontSize: 16, fontWeight: '800', color: colors.navy },
  edit: { fontSize: 12, fontWeight: '700', color: colors.navy2, textDecorationLine: 'underline' },
  detail: { fontSize: 11.5, color: colors.muted, marginTop: 2 },
  tags: { flexDirection: 'row', flexWrap: 'wrap', marginTop: 6 },
  tag: { backgroundColor: colors.redSoft, borderRadius: 6, paddingHorizontal: 6, paddingVertical: 2, marginRight: 4, marginTop: 2 },
  tagText: { fontSize: 10, color: '#94261C' },
  memo: { fontSize: 11, color: colors.muted, marginTop: 6 },
});
