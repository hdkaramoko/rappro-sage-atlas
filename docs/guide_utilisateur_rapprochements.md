# Guide utilisateur

Connectez-vous, puis ajoutez dans **Mon portefeuille** un code déjà connu.

Dans **Mes rapprochements**, deux vues organisent le travail :

- **Envoyé SAGE** s'ouvre sur les lignes à examiner, propositions moteur d'abord.
  Examinez les preuves puis validez ou refusez avec un commentaire. Pour une ligne
  sans correspondance exploitable, utilisez **Rechercher une correspondance**.
  Corriger un montant Atlas et modifier son association Sage sont deux actions
  différentes ; aucune correction ne vaut validation.
- **Contrôle des montants** donne directement accès aux anomalies des pièces.
  Les montants incluent le Comptabilisé et les Envoyé SAGE confirmés. Vous pouvez
  consulter les réconciliés ou tous les contrôles. La fiche distingue le résultat
  courant du diagnostic initial ; une ambiguïté n'est pas résolue par un écart nul.

Pour contester une validation automatique ou manuelle, ouvrez **Réviser le
rapprochement**. Saisissez le motif et confirmez l'annulation, puis recherchez une
autre écriture. Vous pouvez aussi prévisualiser un remplacement et le confirmer
explicitement. L'ancienne décision et les anciennes écritures restent dans
l'historique ; les sources Atlas/Sage ne changent pas. Une campagne historique
reste en consultation seule.

Les filtres **Projet**, **Règle**, **Décision** et **Origine** acceptent plusieurs
choix. **Toutes**, placé en premier, retire la restriction. **Sans correspondance**
se trouve dans Règle. Le compteur et la pagination suivent les filtres ; le lien
de retour conserve la sélection. **Réinitialiser** remet les défauts de l'onglet
actif. Sans JavaScript, décochez Toutes avant de cocher des choix précis.

Les actions compatibles sont reprises au prochain import d'une nouvelle campagne
sur des sources identiques et uniques ; les changements nécessitent confirmation.
Consultez [le parcours détaillé](parcours_metier_rapprochements.md)
pour les exemples, droits et contrôles de sécurité.

Un administrateur charge les fichiers depuis **Imports** et consulte immédiatement le bilan détaillé.

La barre latérale se réduit avec le bouton placé près du logo ; ce choix est conservé dans le navigateur. Sur mobile, le bouton de menu ouvre le volet, qui se ferme en touchant le fond ou avec Échap.

Sur le tableau de bord, sélectionner un projet actualise directement les indicateurs.
Dans Envoyé SAGE, le sélecteur **Lignes** règle la taille de page. L'export
**Corrections validées** conserve le périmètre autorisé de la campagne ; il ne
constitue pas une nouvelle synthèse financière des filtres affichés.
