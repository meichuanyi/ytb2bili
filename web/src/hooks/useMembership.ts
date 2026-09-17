'use client';

import { useCallback, useMemo } from 'react';

export interface MembershipCredits {
  balance: number;
}

export interface MembershipQuota {
  dailyUsed: number;
  dailyUploadLimit: number;
}

export interface MembershipData {
  membership: {
    expiresAt: string | null;
  } | null;
}

export interface UseMembershipReturn {
  tier: string;
  credits: MembershipCredits;
  quota: MembershipQuota;
  membershipData: MembershipData;
  loading: boolean;
  error: null;
  refresh: () => void;
}

/**
 * Stub hook — the membership / credits / payment system has been removed.
 * Returns safe defaults so existing UI code continues to compile and render
 * without crashing. Links to /membership will 404 until the feature is
 * re-introduced.
 *
 * 自托管解锁：会员后端已移除，但部分功能仍按等级锁定（如关闭上传宣传文案）。
 * 此处返回最高等级 enterprise，避免付费功能被永久锁死。
 */
export function useMembership(): UseMembershipReturn {
  const defaults = useMemo<UseMembershipReturn>(
    () => ({
      tier: 'enterprise',
      credits: { balance: 0 },
      quota: { dailyUsed: 0, dailyUploadLimit: 10 },
      membershipData: { membership: null },
      loading: false,
      error: null,
      refresh: () => {
        // no-op — membership backend has been removed
      },
    }),
    [],
  );

  const refresh = useCallback(() => {
    // no-op
  }, []);

  return { ...defaults, refresh };
}

export default useMembership;
