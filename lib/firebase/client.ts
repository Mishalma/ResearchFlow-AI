import { initializeApp, type FirebaseApp } from "firebase/app";
import { getAuth, GoogleAuthProvider, type Auth } from "firebase/auth";

let firebaseApp: FirebaseApp | null = null;
let firebaseAuth: Auth | null = null;

function getFirebaseConfig() {
  return {
    apiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY?.trim() ?? "",
    authDomain: process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN?.trim() ?? "",
    projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID?.trim() ?? "",
    storageBucket: process.env.NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET?.trim() ?? "",
    messagingSenderId:
      process.env.NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID?.trim() ?? "",
    appId: process.env.NEXT_PUBLIC_FIREBASE_APP_ID?.trim() ?? "",
  };
}

export function isFirebaseClientConfigured() {
  const config = getFirebaseConfig();
  return Boolean(
    config.apiKey &&
      config.authDomain &&
      config.projectId &&
      config.appId,
  );
}

export function getFirebaseClientApp() {
  if (!isFirebaseClientConfigured()) {
    throw new Error(
      "Firebase Authentication is not configured. Add the NEXT_PUBLIC_FIREBASE_* environment variables.",
    );
  }

  if (!firebaseApp) {
    firebaseApp = initializeApp(getFirebaseConfig());
  }

  return firebaseApp;
}

export function getFirebaseClientAuth() {
  if (!firebaseAuth) {
    firebaseAuth = getAuth(getFirebaseClientApp());
  }

  return firebaseAuth;
}

export function createGoogleProvider() {
  const provider = new GoogleAuthProvider();
  provider.setCustomParameters({ prompt: "select_account" });
  return provider;
}
