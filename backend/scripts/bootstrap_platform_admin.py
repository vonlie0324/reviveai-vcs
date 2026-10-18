"""One-time local operator-only bootstrap. Requires ADC with Firebase Auth admin permission.

Usage: python scripts/bootstrap_platform_admin.py FIREBASE_UID
Do not run as part of deployment/startup and do not expose via HTTP.
"""
import sys
import firebase_admin
from firebase_admin import auth


def main():
    if len(sys.argv) != 2 or not sys.argv[1].strip():
        raise SystemExit("Usage: python scripts/bootstrap_platform_admin.py FIREBASE_UID")
    uid = sys.argv[1].strip()
    app = firebase_admin.initialize_app(options={"projectId": "ai-projects-250716"})
    user = auth.get_user(uid, app=app)
    print(f"Target UID: {user.uid}; email: {user.email}; existing claims: {user.custom_claims or {}}")
    if input('Type GRANT PLATFORM ADMIN to continue: ').strip() != 'GRANT PLATFORM ADMIN':
        raise SystemExit('Cancelled')
    claims = dict(user.custom_claims or {})
    claims['platform_role'] = 'PLATFORM_ADMIN'
    auth.set_custom_user_claims(uid, claims, app=app)
    print('Admin claim granted. Sign out and sign in again to renew the session cookie.')


if __name__ == '__main__':
    main()
