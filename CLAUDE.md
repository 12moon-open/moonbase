# 12moon commons

Base de métadonnées ouverte, en complément de MusicBrainz, qui commence par les radios. Géré par une seule personne, le mainteneur. **Ce dépôt est public.**

Lire selon le sujet : [modèle de données](docs/data-model.md), [contrat](contract/README.md).

## Règles

- Échanges avec le mainteneur en français, sans exception. Tout ce qui est public (code, documentation, issues, commits) est en anglais.
- **Rien de privé ici** : ni secret, ni clé, ni lien vers un dépôt privé, ni détail sur un produit tiers, ni nom de contributeur. Ce dépôt et son historique sont publics et définitifs. En cas de doute, demander avant d'écrire.
- Ne rien publier, déployer ou créer sur GitHub sans l'accord du mainteneur.
- Faire simple : une seule personne maintient ce service, sans machine à entretenir. Toute nouvelle pièce doit justifier son coût de maintenance.

## Données

- Licence CC0 pour les données et le contrat, MIT pour le code.
- **Sources autorisées uniquement**, listées dans [le modèle de données](docs/data-model.md). Une nouvelle source demande une vérification écrite de sa licence, validée par le mainteneur. Ne jamais importer des données d'un service dont les conditions ne permettent pas la republication.
- Peuvent être publiées : les métadonnées factuelles (titres, crédits, dates, identifiants, liens, stations).
- Jamais : données personnelles, audio, pochettes, images, paroles, critiques, biographies.
- Aucun versement en masse sans validation juridique.
- Chaque fiche se rattache à un identifiant externe quand il existe. Sinon elle reçoit un identifiant 12moon, jamais réutilisé. Une fusion laisse une redirection.

## Architecture

- La lecture passe par des fichiers statiques sur `data.12moon.app`, sans serveur.
- Le dépôt `moondust` est la base publiée. D1 n'est qu'une file d'attente pour les propositions.
- Aucun identifiant de contributeur dans git ni dans un fichier publié.
- Une contribution est une proposition, jamais une écriture directe.
- **Pour la musique, un contributeur anonyme ne propose que des liens entre identifiants** : rien n'est ajouté à MusicBrainz. Voir [docs/contributions.md](docs/contributions.md).
- Deux autres contributions seulement : **l'ajout de stations**, publié après vérification de chaque flux, avec un nom, un lieu et des tags pris dans une liste fermée ; et **les mesures de flux**, anonymes, par semaine, sans durée d'écoute, publiées seulement à partir de trois installations.
- Une adresse de flux est une donnée sensible : toute URL est non fiable, adresses privées refusées.
- Le stable (fiches) et le volatil (état des flux) restent dans des fichiers séparés.

## Contrat

- Changements seulement additifs dans `/v1`. Un vieux client doit continuer à marcher.
- Tout changement de format passe par `contract/`, avec ses cas de test.
- Un client ignore ce qu'il ne connaît pas et continue de marcher sur sa copie locale si le service est coupé.
