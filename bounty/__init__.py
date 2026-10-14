"""Pipeline de chasse aux primes open source (bounties).

Cinq étapes, chacune avec un point d'intervention de l'utilisateur :

    recherche    -> repérage et analyse ; l'utilisateur choisit une tâche
    resolution   -> lecture, reproduction, programmation ; l'utilisateur arbitre
    verification -> tests et relecture ; l'utilisateur vérifie le résultat
    livraison    -> préparation de la PR ; l'utilisateur valide la soumission
    paiement     -> suivi du statut ; l'utilisateur reçoit le paiement

Point d'entrée : ``python -m bounty --help``.
"""

__version__ = "0.1.0"
