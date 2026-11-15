# Ajustements UX du contrôle des montants

L’onglet principal « Contrôle des montants » ouvre désormais les « Comptabilisés incomplets », placés avant les « Contrôles financiers ». Les deux URL directes existantes restent inchangées : `?view=controls&channel=incomplete` et `?view=controls`.

Le bandeau permanent de campagne des contrôles financiers et le paragraphe « Un projet par ligne… » ont été supprimés. Les titres, compteurs et alertes utiles sont conservés.

Les deux listes utilisent une grille de filtres responsive, avec une recherche plus large et des actions alignées. Le tableau des projets conserve trois colonnes : projet à gauche, nombre à droite et action dédiée. Sur mobile, le défilement horizontal reste contenu dans le tableau.

Modifications limitées aux templates et au CSS : aucune règle métier, requête, autorisation ou migration modifiée pour ce correctif UX.

Validation : 52 tests ciblés réussis (parcours incomplets, comptabilisation incomplète, navigation et index des contrôles). Vérification des listes et du détail dans Edge aux largeurs de 390 et 1440 pixels, sans débordement de page. Aucun import de campagne réelle effectué.
