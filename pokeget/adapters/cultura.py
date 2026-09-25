"""Cultura (www.cultura.com).

Le site n'affiche pas ses produits dans le HTML : la page de recherche les
demande ensuite, en JavaScript, à l'API GraphQL publique de la boutique
(Adobe Commerce / Magento), sans compte ni identifiant. pokeget pose la même
question que le navigateur, à la même adresse :

- Recherche : https://www.cultura.com/m2/graphql?query=…&variables=…
  (SEARCH_QUERY ci-dessous est la requête du site, recopiée telle quelle
  depuis /features/plp/data/plp-queries.js : une version raccourcie est
  refusée par l'API).
- Revérification d'un produit : même API, filtrée sur l'adresse du produit
  (réponse de quelques centaines d'octets au lieu d'une fiche de 650 Ko).
- Fiche : https://www.cultura.com/p-<url_key>.html

Disponibilité (« stock_item_extra.front_availability », valeurs relevées
dans /features/product/domain/product-enrichment.js du site) :
  available, available_within_x_days            -> disponible
  available_preorder, available_po_with_date    -> précommande
  unavailable, mag_only (exclu. magasin)        -> rupture
La liste « stock_item_extra.offer » donne le stock des magasins (retrait) :
elle est ignorée, comme sur le site quand aucun magasin n'est choisi.

Cultura est aussi une marketplace (« mp_info.offers ») : quand Cultura n'a
plus le produit mais qu'un revendeur le propose neuf (state_code 11), il est
signalé « vendeur tiers » ; avec « vendeur_officiel_uniquement », seules les
offres de Cultura déclenchent une alerte.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional
from urllib.parse import unquote_plus, urlencode

from pokeget.adapters.retail import RetailerAdapter, to_price
from pokeget.models import Product, Status

OFFICIAL = "Cultura"
NEW = 11  # state_code d'une offre marketplace neuve (1 = occasion)

STATUSES = {
    "available": Status.AVAILABLE,
    "available_within_x_days": Status.AVAILABLE,
    "available_preorder": Status.PREORDER,
    "available_po_with_date": Status.PREORDER,
    "unavailable": Status.OUT,
    "mag_only": Status.OUT,
}

URL_KEY_RE = re.compile(r"/p-([^/?#]+?)\.html")

SEARCH_QUERY = """
query getPlpProducts(
  $currentPage: Int
  $pageSize: Int
  $search: String
  $filter: ProductAttributeFilterInput
  $sort: ProductAttributeSortInput
) {
  products(
    currentPage: $currentPage
    pageSize: $pageSize
    filter: $filter
    sort: $sort
    search: $search
    resolverLight: 1
    noSizeLimitation: "color_affiliation"
  ) {
    redirect_url
    total_count
    lowest_price
    highest_price
    is_spellchecked
    query_id
    global_expanded_facets
    page_info {
      category {
        label
        value
        path
      }
      color_affiliation {
        label
        value
      }
      seller_name {
        label
        value
      }
      page_size
      current_page
      total_pages
    }
    items {
      id
      sku
      name
      kit_nb_options
      kit_image {
        url
        label
      }
      image {
        name
        url
      }
      small_image {
        url
      }
      url_key
      type_id
      ebookType
      cross_format
      cross_format_label
      ean
      erp_product_code
      rating
      nb_reviews
      front_subtitle
      main_flag {
        label
        value
      }
      mp_info {
        offers {
          offer_id
          product_sku
          quantity
          shop {
            name
            id
            url_key
          }
          ranking
          price
          total_price
          origin_price
          state_code
        }
        total_new
        total_used
        lowest_price_new {
          value
        }
        lowest_price_used {
          value
        }
        second_lowest_price_new {
          value
        }
        second_lowest_price_used {
          value
        }
      }
      price_range {
        minimum_price {
          regular_price {
            value
            currency
          }
          final_price {
            value
            currency
          }
          discount {
            amount_off
            percent_off
          }
          final_price_excl_tax {
            value
            currency
          }
        }
        maximum_price {
          regular_price {
            value
            currency
          }
          final_price {
            value
            currency
          }
          discount {
            amount_off
            percent_off
          }
        }
      }
      cultura_review {
        review_id
        title
        detail
        nickname
        cultura_store_name
      }
      ... on ConfigurableProduct {
        price_range {
          maximum_price {
            regular_price {
              value
              currency
            }
            final_price {
              value
              currency
            }
            discount {
              amount_off
              percent_off
            }
          }
        }
      }
      ... on BundleProduct {
        items {
          option_id
          options {
            label
            quantity
            can_change_quantity
            price
            product {
              name
              nb_reviews
              url_key
              rating
              sku
              stock_status
              ean
              erp_product_code
              image {
                url
                label
              }
              price_range {
                minimum_price {
                  regular_price {
                    value
                    currency
                  }
                  final_price {
                    value
                    currency
                  }
                  discount {
                    amount_off
                    percent_off
                  }
                  final_price_excl_tax {
                    value
                    currency
                  }
                }
              }
            }
          }
        }
      }
      attribute_set_id
      attribute_set_name
      release_date
      backorder_end_date
      stock_item_extra {
        front_availability
        availability_date
        order_delay
        min_quantity_in_cart
        offer {
          front_availability
          seller_code
          qty
        }
      }
      book_support
      support_musical_custom_: support_musical
      support_video_custom_: support_video
      format_book_custom_: format_book
      button_id_custom_: button_id
      special_price_custom_: special_price
    }
    aggregations {
      options {
        count
        label
        value
      }
      attribute_code
      count
      label
      is_swatch
      expanded_mode
    }
  }
  categories(search: $search, pageSize: 5, has_product: 1) {
    items {
      entity_id
      name
    }
  }
  entities(
    search: $search
    pageSize: 2
    resolverLight: 1
    filter: { has_product: { eq: 1 } }
  ) {
    items {
      label
      entity_id
      image_1
    }
  }
}
"""

PRODUCT_QUERY = """
query getProduct($filter: ProductAttributeFilterInput) {
  products(currentPage: 1, pageSize: 1, filter: $filter, resolverLight: 1, noSizeLimitation: "color_affiliation") {
    items {
      sku
      name
      url_key
      price_range { minimum_price { final_price { value } } }
      stock_item_extra { front_availability }
      mp_info { offers { price state_code shop { name } } }
    }
  }
}
"""


class CulturaAdapter(RetailerAdapter):
    kind = "cultura"
    marketplace = True
    request_headers = {"Store": "cultura_b2c_fr_FR"}  # en-tête envoyé par le site lui-même

    def graphql_url(self, query: str, variables: Dict[str, Any]) -> str:
        params = urlencode({"query": query, "variables": json.dumps(variables, ensure_ascii=False)})
        return f"{self.base_url}/m2/graphql?{params}"

    def search_url(self, term: str) -> str:
        return self.graphql_url(SEARCH_QUERY, {
            "currentPage": 1, "pageSize": 60, "search": unquote_plus(term),
            # filtres posés par le site sur toutes ses recherches
            "filter": {"has_image": {"eq": "true"}, "data_source": {"in": [""]}},
        })

    def check_url(self, product: Product) -> str:
        return self.graphql_url(PRODUCT_QUERY, {
            "filter": {"url_key": {"eq": product.pid}, "data_source": {"in": [""]}}})

    def pid_from_url(self, url: str) -> str:
        m = URL_KEY_RE.search(url)
        return m.group(1) if m else url

    @staticmethod
    def items(page: str) -> List[Dict[str, Any]]:
        try:
            data = json.loads(page)
        except ValueError:
            raise RuntimeError("réponse Cultura illisible (pas du JSON)")
        products = (data.get("data") or {}).get("products")
        if products is None:
            errors = "; ".join(e.get("message", "?") for e in data.get("errors") or [])
            raise RuntimeError(f"réponse Cultura inattendue : {errors or 'aucun produit'}")
        return products.get("items") or []

    def product(self, item: Dict[str, Any]) -> Product:
        url_key = item["url_key"]
        url = f"{self.base_url}/p-{url_key}.html"
        availability = (item.get("stock_item_extra") or {}).get("front_availability")
        status = STATUSES.get(availability, Status.UNKNOWN)
        price = to_price((((item.get("price_range") or {}).get("minimum_price") or {})
                          .get("final_price") or {}).get("value"))
        seller, official = OFFICIAL, True
        if availability == "unavailable":  # comme le site : pas de repli marketplace si « exclu. magasin »
            offers = [o for o in (item.get("mp_info") or {}).get("offers") or []
                      if o.get("state_code") == NEW and to_price(o.get("price")) is not None]
            if offers:  # Cultura n'en a plus, mais un revendeur le vend neuf
                best = min(offers, key=lambda o: to_price(o["price"]))
                status, price = Status.AVAILABLE, to_price(best["price"])
                seller, official = ((best.get("shop") or {}).get("name") or "revendeur"), False
        p = self.make_product(url_key, item.get("name") or url_key, url, status, price,
                              sku=item.get("sku"), availability=availability)
        p.seller, p.official_seller = seller, official
        return p

    def parse_search(self, page: str) -> List[Product]:
        return [self.product(it) for it in self.items(page) if it.get("url_key")]

    def parse_product(self, page: str, url: str) -> Optional[Product]:
        pid = self.pid_from_url(url)
        items = [it for it in self.items(page) if it.get("url_key") == pid]
        return self.product(items[0]) if items else None
