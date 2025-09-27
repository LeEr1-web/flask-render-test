document.addEventListener('DOMContentLoaded', function() {
  // ===== FILTRAGE DES SECTIONS DANS LA SIDEBAR =====
  const sidebarSectionToggles = document.querySelectorAll('.sidebar-section-toggle');
  const sidebarSections = document.querySelectorAll('.sidebar-section');

  function showSidebarSection(key) {
    // Mettre à jour les boutons actifs
    sidebarSectionToggles.forEach(btn => {
      btn.classList.remove('active');
      if (btn.dataset.target === key) {
        btn.classList.add('active');
      }
    });

    // Afficher/masquer les sections
    sidebarSections.forEach(section => {
      section.classList.remove('active');
      if (key === 'all' || section.dataset.key === key) {
        section.classList.add('active');
      }
    });
  }

  // Ajouter les événements aux boutons de la sidebar
  sidebarSectionToggles.forEach(btn => {
    btn.addEventListener('click', function() {
      const target = this.dataset.target;
      showSidebarSection(target);
    });
  });

  // ===== FILTRAGE DES MARQUES DANS LA SIDEBAR (ancien système) =====
  const brandSearch = document.getElementById('brand-search');
  const categoryFilter = document.getElementById('category-filter');
  const brandItems = Array.from(document.querySelectorAll('#brand-list .brand-item'));

  function filterBrands() {
    const q = brandSearch ? brandSearch.value.trim().toLowerCase() : '';
    const sel = categoryFilter ? categoryFilter.value : '';
    
    brandItems.forEach(li => {
      const title = li.dataset.title || '';
      const header = (li.dataset.header || '').toLowerCase();
      let visible = true;
      
      if (sel && sel !== '__all__') {
        const selLower = sel.toLowerCase();
        if (header) {
          visible = header.includes(selLower);
        } else {
          visible = title.includes(selLower) || title.includes(selLower.split(' ').slice(-1)[0]);
        }
      }
      
      if (q) {
        visible = visible && title.includes(q);
      }
      
      li.style.display = visible ? '' : 'none';
    });
  }

  if (brandSearch) {
    brandSearch.addEventListener('input', filterBrands);
  }
  if (categoryFilter) {
    categoryFilter.addEventListener('change', filterBrands);
  }

  // ===== SECTIONS RAPIDES DE LA PAGE D'ACCUEIL =====
  const sectionButtons = Array.from(document.querySelectorAll('.section-toggle'));
  const sections = Array.from(document.querySelectorAll('.quick-section'));

  function showSection(key) {
    sections.forEach(s => {
      if (key === 'all' || s.dataset.key === key) {
        s.style.display = '';
      } else {
        s.style.display = 'none';
      }
    });
    
    // Mettre à jour les boutons actifs
    sectionButtons.forEach(btn => {
      btn.classList.remove('active');
      if (btn.dataset.target === key) {
        btn.classList.add('active');
      } else if (key === 'all' && btn.dataset.target === 'all') {
        btn.classList.add('active');
      }
    });
  }

  // Ajouter les événements aux boutons de la page d'accueil
  sectionButtons.forEach(btn => {
    btn.addEventListener('click', function() {
      const target = this.dataset.target;
      showSection(target);
      
      // Scroll vers la section
      const quick = document.getElementById('quick-sections');
      if (quick) quick.scrollIntoView({behavior:'smooth', block:'start'});
    });
  });

  // Gérer l'affichage initial des sections "no-items"
  sections.forEach(s => {
    const no = s.querySelector('.no-items');
    if (no) {
      no.style.display = s.style.display === 'none' ? 'none' : '';
    }
  });

  // ===== FONCTIONNALITÉS SUPPLEMENTAIRES =====
  
  // Recherche en temps réel dans les sections de la sidebar
  const sidebarSearch = document.getElementById('sidebar-search');
  if (sidebarSearch) {
    sidebarSearch.addEventListener('input', function() {
      const query = this.value.toLowerCase().trim();
      const activeSection = document.querySelector('.sidebar-section.active');
      
      if (activeSection) {
        const items = activeSection.querySelectorAll('.sidebar-section-item');
        items.forEach(item => {
          const text = item.textContent.toLowerCase();
          item.style.display = text.includes(query) ? '' : 'none';
        });
      }
    });
  }

  // Animation au survol des éléments de la sidebar
  const sidebarItems = document.querySelectorAll('.sidebar-section-item');
  sidebarItems.forEach(item => {
    item.addEventListener('mouseenter', function() {
      this.style.transform = 'translateX(5px)';
    });
    
    item.addEventListener('mouseleave', function() {
      this.style.transform = 'translateX(0)';
    });
  });

  console.log('Sidebar sections system initialized');
});