const state = {
  models: [],
  installed: [],
  currentSession: null,
  chatMessages: [],
  uploadedFiles: [],
  activeView: "homeView",
  pullTasks: {},
  pullPolls: {},
  deleteTasks: {},
  deletePolls: {},
  tokenUsage: null,
  agentsMode: false,
  projects: [],
  currentProject: null,
  projectSources: [],
  researchers: [],
  currentResearcher: null,
  allSessions: [],
  lastSystemPayload: null,
  lastToolsPayload: null,
};

let activeChatRequest = null;

const STORAGE_KEY = "ci2lab.ui.state.v1";
const LANGUAGE_KEY = "ci2lab.ui.language";
const INTERNAL_LANGUAGE = "en";
const SUPPORTED_LANGUAGES = ["en", "es", "fr", "pt"];
let currentLanguage = localStorage.getItem(LANGUAGE_KEY) || "en";
if (!SUPPORTED_LANGUAGES.includes(currentLanguage)) currentLanguage = "en";
const NO_AUTO_TRANSLATE_SELECTOR = "#messages, .message, .process-log, [data-no-translate]";
const originalTextNodes = new WeakMap();
const originalAttributes = new WeakMap();
const LANGUAGE_LABELS = {
  en: "English",
  es: "Español",
  fr: "Français",
  pt: "Português",
};

const LANGUAGE_LOCALES = {
  en: "en",
  es: "es-ES",
  fr: "fr-FR",
  pt: "pt-PT",
};

const SPANISH_TRANSLATIONS = {
  "Main navigation": "Navegación principal",
  "Home sections": "Secciones de inicio",
  "Home": "Inicio",
  "Local models": "Modelos locales",
  "Sessions": "Sesiones",
  "Chat": "Chat",
  "My projects": "Mis proyectos",
  "Change language": "Cambiar idioma",
  "Change interface language": "Cambiar idioma de la interfaz",
  "Local status": "Estado local",
  "Checking...": "Comprobando...",
  "Ollama unavailable": "Ollama no disponible",
  "Ollama API not configured": "API de Ollama no configurada",
  "Executable not found in PATH": "Ejecutable no encontrado en PATH",
  "Models folder not detected": "Carpeta de modelos no detectada",
  "Local multi-model agent": "Agente multimodelo local",
  "Interact with Florentino without opening the terminal": "Interactúa con Florentino sin abrir el terminal",
  "Refresh data": "Actualizar datos",
  "Refresh Ollama status, hardware, models and sessions": "Actualizar el estado de Ollama, el hardware, los modelos y las sesiones",
  "Explain refresh data": "Explicar la actualización de datos",
  "View explanation": "Ver explicación",
  "Reloads models, sessions, hardware and Ollama's local status.": "Recarga los modelos, las sesiones, el hardware y el estado local de Ollama.",
  "Your machine": "Tu equipo",
  "Local capacity and recommended models": "Capacidad local y modelos recomendados",
  "Scanning hardware...": "Analizando el hardware...",
  "Computer check": "Comprobación del equipo",
  "Memory, disk and local mode": "Memoria, disco y modo local",
  "Available RAM": "RAM disponible",
  "Free disk": "Disco libre",
  "AI budget": "Capacidad para IA",
  "Inference mode": "Modo de inferencia",
  "CPU only": "Solo CPU",
  "Recommended models": "Modelos recomendados",
  "Options that fit this machine best": "Las opciones que mejor encajan en este equipo",
  "Ollama + catalog": "Ollama + catálogo",
  "Models": "Modelos",
  "Filter model...": "Filtrar modelo...",
  "Local history": "Historial local",
  "Independent knowledge spaces": "Espacios de conocimiento independientes",
  "Organize sources and conversations by subject, course or recurring task.": "Organiza fuentes y conversaciones por tema, curso o tarea recurrente.",
  "New project": "Nuevo proyecto",
  "Project name": "Nombre del proyecto",
  "For example: Machine learning": "Por ejemplo: Aprendizaje automático",
  "Cancel": "Cancelar",
  "Create project": "Crear proyecto",
  "Active project": "Proyecto activo",
  "Project": "Proyecto",
  "New chat": "Nuevo chat",
  "Reference material": "Material de referencia",
  "Project sources": "Fuentes del proyecto",
  "These documents are used as reference in every chat inside this project.": "Estos documentos se usan como referencia en todos los chats de este proyecto.",
  "Add project sources": "Añadir fuentes al proyecto",
  "Add sources": "Añadir fuentes",
  "Project history": "Historial del proyecto",
  "Conversations": "Conversaciones",
  "Continue any previous chat without leaving this project's context.": "Continúa cualquier chat anterior sin salir del contexto de este proyecto.",
  "Knowledge project": "Proyecto de conocimiento",
  "Outside projects": "Fuera de proyectos",
  "Model": "Modelo",
  "See how tokens are counted": "Ver cómo se cuentan los tokens",
  "Tokens": "Tokens",
  "New": "Nuevo",
  "Refresh": "Actualizar",
  "Start a clean conversation without mixing it with the current session": "Iniciar una conversación limpia sin mezclarla con la sesión actual",
  "Tools and integrations": "Herramientas e integraciones",
  "View sources": "Ver fuentes",
  "Prompt suggestions": "Sugerencias de prompts",
  "Open prompt suggestions": "Abrir sugerencias de prompts",
  "Enable sequential subagents": "Activar subagentes secuenciales",
  "Agents": "Agentes",
  "Attach file": "Adjuntar archivo",
  "Type a request for the local agent...": "Escribe una petición para el agente local...",
  "Send": "Enviar",
  "Tools": "Herramientas",
  "Explore": "Explorar",
  "Edit": "Editar",
  "Git": "Git",
  "Planning": "Planificación",
  "Web": "Web",
  "Notebook": "Notebook",
  "Skills": "Skills",
  "MCP": "MCP",
  "System": "Sistema",
  "Other": "Otros",
  "Close tools": "Cerrar herramientas",
  "Close": "Cerrar",
  "Loading tools...": "Cargando herramientas...",
  "Loaded skills": "Skills cargadas",
  "Configured MCP servers": "Servidores MCP configurados",
  "Token usage": "Uso de tokens",
  "Conversation counter": "Contador de la conversación",
  "Back to chat": "Volver al chat",
  "Last turn input": "Entrada del último turno",
  "Prompt, history and context sent to the model.": "Prompt, historial y contexto enviados al modelo.",
  "Last turn output": "Salida del último turno",
  "Text generated by the model.": "Texto generado por el modelo.",
  "Last turn total": "Total del último turno",
  "Input + output.": "Entrada + salida.",
  "Conversation total": "Total de la conversación",
  "Cumulative sum of calls in the current chat.": "Suma acumulada de llamadas en el chat actual.",
  "Calculation": "Cálculo",
  "Total = input tokens + output tokens. The values come from the local provider when Ollama returns them.": "Total = tokens de entrada + tokens de salida. Los valores proceden del proveedor local cuando Ollama los devuelve.",
  "Family": "Familia",
  "Max context": "Contexto máximo",
  "Tool mode": "Modo de herramientas",
  "Best practices": "Buenas prácticas",
  "Start a new chat when the previous history no longer adds context.": "Inicia un chat nuevo cuando el historial anterior ya no aporte contexto.",
  "Summarize long documents before requesting several tasks on them.": "Resume los documentos largos antes de pedir varias tareas sobre ellos.",
  "Attach only the files and fragments needed for the question.": "Adjunta solo los archivos y fragmentos necesarios para la consulta.",
  "Avoid pasting the same content multiple times in the conversation.": "Evita pegar el mismo contenido varias veces en la conversación.",
  "More information:": "Más información:",
  "and": "y",
  "Turn 0": "Turno 0",
  "Conversation 0": "Conversación 0",
  "Process": "Proceso",
  "Warning": "Aviso",
  "Ready. Type your request or attach files.": "Listo. Escribe tu petición o adjunta archivos.",
  "Session ready": "Sesión lista",
  "Stop": "Detener",
  "Stop current response": "Detener la respuesta actual",
  "Send message": "Enviar mensaje",
  "Florentino local": "Florentino local",
  "Start a conversation": "Inicia una conversación",
  "Try: \"summarize this project\" or \"list the Python files\".": "Prueba: «resume este proyecto» o «enumera los archivos Python».",
  "Deciding the next step...": "Decidiendo el siguiente paso...",
  "Reading the attached files...": "Leyendo los archivos adjuntos...",
  "Extracting information from the PDF...": "Extrayendo información del PDF...",
  "Reading the document...": "Leyendo el documento...",
  "Planning the code change...": "Planificando el cambio de código...",
  "Generating code changes...": "Generando cambios de código...",
  "Looking up current information...": "Buscando información actualizada...",
  "Checking the result...": "Comprobando el resultado...",
  "Preparing the answer...": "Preparando la respuesta...",
  "Agents on": "Agentes activos",
  "Local PDF or text": "PDF o texto local",
  "Attachments:": "Adjuntos:",
  "Remove file": "Quitar archivo",
  "Use": "Usar",
  "Delete": "Eliminar",
  "Download": "Descargar",
  "Installed": "Instalado",
  "(not installed)": "(no instalado)",
  "No saved sessions yet.": "Todavía no hay sesiones guardadas.",
  "Conversation": "Conversación",
  "Resume": "Reanudar",
  "Delete saved conversation": "Eliminar conversación guardada",
  "No projects yet": "Todavía no hay proyectos",
  "Create one to keep sources and conversations for a subject together.": "Crea uno para mantener juntas las fuentes y conversaciones de un tema.",
  "Remove": "Quitar",
  "Remove source": "Quitar fuente",
  "Delete conversation": "Eliminar conversación",
  "No sources yet. Add notes, slides, PDFs or other course material.": "Todavía no hay fuentes. Añade apuntes, diapositivas, PDF u otro material.",
  "No sources yet": "Todavía no hay fuentes",
  "Add notes, slides, PDFs or other course material. Every chat in this project will use them as reference.": "Añade apuntes, diapositivas, PDF u otro material. Todos los chats de este proyecto los usarán como referencia.",
  "Add first source": "Añadir primera fuente",
  "No conversations yet": "Todavía no hay conversaciones",
  "Start a chat and the model will use this project's sources as its reference base.": "Inicia un chat y el modelo usará las fuentes de este proyecto como referencia.",
  "Hide sources": "Ocultar fuentes",
  "Refreshing": "Actualizando",
  "Deleting...": "Eliminando...",
  "Starting...": "Iniciando...",
  "Downloading": "Descargando",
  "Uninstalling": "Desinstalando",
  "Calculating size...": "Calculando tamaño...",
  "Ollama updated": "Ollama actualizado",
  "Removing local files...": "Eliminando archivos locales...",
  "Could not read the hardware.": "No se pudo leer el hardware.",
  "Memory is under pressure: closing apps may allow larger models.": "La memoria está bajo presión: cerrar aplicaciones puede permitir modelos más grandes.",
  "Your machine is ready for compatible local models.": "Tu equipo está listo para modelos locales compatibles.",
  "No recommendations available right now.": "No hay recomendaciones disponibles ahora mismo.",
  "Could not load the tools.": "No se pudieron cargar las herramientas.",
  "API": "API",
  "App": "App",
  "Models": "Modelos",
  "UI error": "Error de interfaz",
};

const FRENCH_TRANSLATIONS = {
  "Main navigation": "Navigation principale",
  "Home sections": "Sections d'accueil",
  "Home": "Accueil",
  "Local models": "Modèles locaux",
  "Sessions": "Sessions",
  "Chat": "Chat",
  "My projects": "Mes projets",
  "Change language": "Changer de langue",
  "Change interface language": "Changer la langue de l'interface",
  "Local status": "État local",
  "Checking...": "Vérification...",
  "Ollama unavailable": "Ollama indisponible",
  "Ollama API not configured": "API Ollama non configurée",
  "Executable not found in PATH": "Exécutable introuvable dans PATH",
  "Models folder not detected": "Dossier des modèles non détecté",
  "Local multi-model agent": "Agent multimodèle local",
  "Interact with Florentino without opening the terminal": "Interagissez avec Florentino sans ouvrir le terminal",
  "Refresh data": "Actualiser les données",
  "Refresh Ollama status, hardware, models and sessions": "Actualiser l'état d'Ollama, le matériel, les modèles et les sessions",
  "Explain refresh data": "Expliquer l'actualisation",
  "View explanation": "Voir l'explication",
  "Reloads models, sessions, hardware and Ollama's local status.": "Recharge les modèles, les sessions, le matériel et l'état local d'Ollama.",
  "Your machine": "Votre machine",
  "Local capacity and recommended models": "Capacité locale et modèles recommandés",
  "Scanning hardware...": "Analyse du matériel...",
  "Computer check": "Vérification de l'ordinateur",
  "Memory, disk and local mode": "Mémoire, disque et mode local",
  "Available RAM": "RAM disponible",
  "Free disk": "Disque libre",
  "AI budget": "Budget IA",
  "Inference mode": "Mode d'inférence",
  "CPU only": "CPU uniquement",
  "Recommended models": "Modèles recommandés",
  "Options that fit this machine best": "Options les mieux adaptées à cette machine",
  "Ollama + catalog": "Ollama + catalogue",
  "Models": "Modèles",
  "Filter model...": "Filtrer le modèle...",
  "Local history": "Historique local",
  "Independent knowledge spaces": "Espaces de connaissance indépendants",
  "Organize sources and conversations by subject, course or recurring task.": "Organisez les sources et conversations par sujet, cours ou tâche récurrente.",
  "New project": "Nouveau projet",
  "Project name": "Nom du projet",
  "For example: Machine learning": "Par exemple : apprentissage automatique",
  "Cancel": "Annuler",
  "Create project": "Créer le projet",
  "Active project": "Projet actif",
  "Project": "Projet",
  "New chat": "Nouveau chat",
  "Reference material": "Documents de référence",
  "Project sources": "Sources du projet",
  "These documents are used as reference in every chat inside this project.": "Ces documents servent de référence dans chaque chat de ce projet.",
  "Add project sources": "Ajouter des sources au projet",
  "Add sources": "Ajouter des sources",
  "Project history": "Historique du projet",
  "Conversations": "Conversations",
  "Continue any previous chat without leaving this project's context.": "Continuez un chat précédent sans quitter le contexte de ce projet.",
  "Knowledge project": "Projet de connaissance",
  "Outside projects": "Hors projets",
  "Model": "Modèle",
  "See how tokens are counted": "Voir comment les tokens sont comptés",
  "Tokens": "Tokens",
  "New": "Nouveau",
  "Refresh": "Actualiser",
  "Start a clean conversation without mixing it with the current session": "Démarrer une conversation propre sans la mélanger avec la session actuelle",
  "Tools and integrations": "Outils et intégrations",
  "View sources": "Voir les sources",
  "Prompt suggestions": "Suggestions de prompts",
  "Open prompt suggestions": "Ouvrir les suggestions de prompts",
  "Enable sequential subagents": "Activer les sous-agents séquentiels",
  "Agents": "Agents",
  "Attach file": "Joindre un fichier",
  "Type a request for the local agent...": "Saisissez une demande pour l'agent local...",
  "Send": "Envoyer",
  "Tools": "Outils",
  "Explore": "Explorer",
  "Edit": "Modifier",
  "Git": "Git",
  "Planning": "Planification",
  "Web": "Web",
  "Notebook": "Notebook",
  "Skills": "Skills",
  "MCP": "MCP",
  "System": "Système",
  "Other": "Autres",
  "Close tools": "Fermer les outils",
  "Close": "Fermer",
  "Loading tools...": "Chargement des outils...",
  "Loaded skills": "Skills chargées",
  "Configured MCP servers": "Serveurs MCP configurés",
  "Token usage": "Utilisation des tokens",
  "Conversation counter": "Compteur de conversation",
  "Back to chat": "Retour au chat",
  "Last turn input": "Entrée du dernier tour",
  "Prompt, history and context sent to the model.": "Prompt, historique et contexte envoyés au modèle.",
  "Last turn output": "Sortie du dernier tour",
  "Text generated by the model.": "Texte généré par le modèle.",
  "Last turn total": "Total du dernier tour",
  "Input + output.": "Entrée + sortie.",
  "Conversation total": "Total de la conversation",
  "Cumulative sum of calls in the current chat.": "Somme cumulée des appels dans le chat actuel.",
  "Calculation": "Calcul",
  "Total = input tokens + output tokens. The values come from the local provider when Ollama returns them.": "Total = tokens d'entrée + tokens de sortie. Les valeurs viennent du fournisseur local lorsqu'Ollama les renvoie.",
  "Family": "Famille",
  "Max context": "Contexte max",
  "Tool mode": "Mode outils",
  "Best practices": "Bonnes pratiques",
  "Start a new chat when the previous history no longer adds context.": "Démarrez un nouveau chat lorsque l'historique précédent n'apporte plus de contexte.",
  "Summarize long documents before requesting several tasks on them.": "Résumez les longs documents avant de demander plusieurs tâches dessus.",
  "Attach only the files and fragments needed for the question.": "Joignez seulement les fichiers et fragments nécessaires à la question.",
  "Avoid pasting the same content multiple times in the conversation.": "Évitez de coller le même contenu plusieurs fois dans la conversation.",
  "More information:": "Plus d'informations :",
  "and": "et",
  "Turn 0": "Tour 0",
  "Conversation 0": "Conversation 0",
  "Process": "Processus",
  "Warning": "Avertissement",
  "Ready. Type your request or attach files.": "Prêt. Saisissez votre demande ou joignez des fichiers.",
  "Session ready": "Session prête",
  "Stop": "Arrêter",
  "Stop current response": "Arrêter la réponse en cours",
  "Send message": "Envoyer le message",
  "Florentino local": "Florentino local",
  "Start a conversation": "Démarrer une conversation",
  "Try: \"summarize this project\" or \"list the Python files\".": "Essayez : « résume ce projet » ou « liste les fichiers Python ».",
  "Deciding the next step...": "Décision de la prochaine étape...",
  "Reading the attached files...": "Lecture des fichiers joints...",
  "Extracting information from the PDF...": "Extraction des informations du PDF...",
  "Reading the document...": "Lecture du document...",
  "Planning the code change...": "Planification du changement de code...",
  "Generating code changes...": "Génération des changements de code...",
  "Looking up current information...": "Recherche d'informations à jour...",
  "Checking the result...": "Vérification du résultat...",
  "Preparing the answer...": "Préparation de la réponse...",
  "Agents on": "Agents activés",
  "Local PDF or text": "PDF ou texte local",
  "Attachments:": "Pièces jointes :",
  "Remove file": "Retirer le fichier",
  "Use": "Utiliser",
  "Delete": "Supprimer",
  "Download": "Télécharger",
  "Installed": "Installé",
  "(not installed)": "(non installé)",
  "No saved sessions yet.": "Aucune session enregistrée pour le moment.",
  "Conversation": "Conversation",
  "Resume": "Reprendre",
  "Delete saved conversation": "Supprimer la conversation enregistrée",
  "No projects yet": "Aucun projet pour le moment",
  "Create one to keep sources and conversations for a subject together.": "Créez-en un pour regrouper sources et conversations d'un même sujet.",
  "Remove": "Retirer",
  "Remove source": "Retirer la source",
  "Delete conversation": "Supprimer la conversation",
  "No sources yet. Add notes, slides, PDFs or other course material.": "Aucune source pour le moment. Ajoutez des notes, diapositives, PDF ou autres supports de cours.",
  "No sources yet": "Aucune source pour le moment",
  "Add notes, slides, PDFs or other course material. Every chat in this project will use them as reference.": "Ajoutez des notes, diapositives, PDF ou autres supports de cours. Chaque chat de ce projet les utilisera comme référence.",
  "Add first source": "Ajouter la première source",
  "No conversations yet": "Aucune conversation pour le moment",
  "Start a chat and the model will use this project's sources as its reference base.": "Démarrez un chat et le modèle utilisera les sources de ce projet comme base de référence.",
  "Hide sources": "Masquer les sources",
  "Refreshing": "Actualisation",
  "Deleting...": "Suppression...",
  "Starting...": "Démarrage...",
  "Downloading": "Téléchargement",
  "Uninstalling": "Désinstallation",
  "Calculating size...": "Calcul de la taille...",
  "Ollama updated": "Ollama mis à jour",
  "Removing local files...": "Suppression des fichiers locaux...",
  "Could not read the hardware.": "Impossible de lire le matériel.",
  "Memory is under pressure: closing apps may allow larger models.": "La mémoire est sous pression : fermer des applications peut permettre d'utiliser des modèles plus grands.",
  "Your machine is ready for compatible local models.": "Votre machine est prête pour les modèles locaux compatibles.",
  "No recommendations available right now.": "Aucune recommandation disponible pour le moment.",
  "Could not load the tools.": "Impossible de charger les outils.",
  "API": "API",
  "App": "App",
  "Models": "Modèles",
  "UI error": "Erreur d'interface",
};

const PORTUGUESE_TRANSLATIONS = {
  "Main navigation": "Navegação principal",
  "Home sections": "Secções iniciais",
  "Home": "Início",
  "Local models": "Modelos locais",
  "Sessions": "Sessões",
  "Chat": "Chat",
  "My projects": "Os meus projetos",
  "Change language": "Alterar idioma",
  "Change interface language": "Alterar idioma da interface",
  "Local status": "Estado local",
  "Checking...": "A verificar...",
  "Ollama unavailable": "Ollama indisponível",
  "Ollama API not configured": "API do Ollama não configurada",
  "Executable not found in PATH": "Executável não encontrado no PATH",
  "Models folder not detected": "Pasta de modelos não detetada",
  "Local multi-model agent": "Agente multimodelo local",
  "Interact with Florentino without opening the terminal": "Interaja com o Florentino sem abrir o terminal",
  "Refresh data": "Atualizar dados",
  "Refresh Ollama status, hardware, models and sessions": "Atualizar estado do Ollama, hardware, modelos e sessões",
  "Explain refresh data": "Explicar atualização de dados",
  "View explanation": "Ver explicação",
  "Reloads models, sessions, hardware and Ollama's local status.": "Recarrega modelos, sessões, hardware e o estado local do Ollama.",
  "Your machine": "A sua máquina",
  "Local capacity and recommended models": "Capacidade local e modelos recomendados",
  "Scanning hardware...": "A analisar o hardware...",
  "Computer check": "Verificação do computador",
  "Memory, disk and local mode": "Memória, disco e modo local",
  "Available RAM": "RAM disponível",
  "Free disk": "Disco livre",
  "AI budget": "Capacidade para IA",
  "Inference mode": "Modo de inferência",
  "CPU only": "Apenas CPU",
  "Recommended models": "Modelos recomendados",
  "Options that fit this machine best": "Opções que melhor se ajustam a esta máquina",
  "Ollama + catalog": "Ollama + catálogo",
  "Models": "Modelos",
  "Filter model...": "Filtrar modelo...",
  "Local history": "Histórico local",
  "Independent knowledge spaces": "Espaços de conhecimento independentes",
  "Organize sources and conversations by subject, course or recurring task.": "Organize fontes e conversas por assunto, disciplina ou tarefa recorrente.",
  "New project": "Novo projeto",
  "Project name": "Nome do projeto",
  "For example: Machine learning": "Por exemplo: aprendizagem automática",
  "Cancel": "Cancelar",
  "Create project": "Criar projeto",
  "Active project": "Projeto ativo",
  "Project": "Projeto",
  "New chat": "Novo chat",
  "Reference material": "Material de referência",
  "Project sources": "Fontes do projeto",
  "These documents are used as reference in every chat inside this project.": "Estes documentos são usados como referência em todos os chats deste projeto.",
  "Add project sources": "Adicionar fontes ao projeto",
  "Add sources": "Adicionar fontes",
  "Project history": "Histórico do projeto",
  "Conversations": "Conversas",
  "Continue any previous chat without leaving this project's context.": "Continue qualquer chat anterior sem sair do contexto deste projeto.",
  "Knowledge project": "Projeto de conhecimento",
  "Outside projects": "Fora dos projetos",
  "Model": "Modelo",
  "See how tokens are counted": "Ver como os tokens são contados",
  "Tokens": "Tokens",
  "New": "Novo",
  "Refresh": "Atualizar",
  "Start a clean conversation without mixing it with the current session": "Iniciar uma conversa limpa sem a misturar com a sessão atual",
  "Tools and integrations": "Ferramentas e integrações",
  "View sources": "Ver fontes",
  "Prompt suggestions": "Sugestões de prompts",
  "Open prompt suggestions": "Abrir sugestões de prompts",
  "Enable sequential subagents": "Ativar subagentes sequenciais",
  "Agents": "Agentes",
  "Attach file": "Anexar ficheiro",
  "Type a request for the local agent...": "Escreva um pedido para o agente local...",
  "Send": "Enviar",
  "Tools": "Ferramentas",
  "Explore": "Explorar",
  "Edit": "Editar",
  "Git": "Git",
  "Planning": "Planeamento",
  "Web": "Web",
  "Notebook": "Notebook",
  "Skills": "Skills",
  "MCP": "MCP",
  "System": "Sistema",
  "Other": "Outros",
  "Close tools": "Fechar ferramentas",
  "Close": "Fechar",
  "Loading tools...": "A carregar ferramentas...",
  "Loaded skills": "Skills carregadas",
  "Configured MCP servers": "Servidores MCP configurados",
  "Token usage": "Uso de tokens",
  "Conversation counter": "Contador da conversa",
  "Back to chat": "Voltar ao chat",
  "Last turn input": "Entrada do último turno",
  "Prompt, history and context sent to the model.": "Prompt, histórico e contexto enviados ao modelo.",
  "Last turn output": "Saída do último turno",
  "Text generated by the model.": "Texto gerado pelo modelo.",
  "Last turn total": "Total do último turno",
  "Input + output.": "Entrada + saída.",
  "Conversation total": "Total da conversa",
  "Cumulative sum of calls in the current chat.": "Soma acumulada das chamadas no chat atual.",
  "Calculation": "Cálculo",
  "Total = input tokens + output tokens. The values come from the local provider when Ollama returns them.": "Total = tokens de entrada + tokens de saída. Os valores vêm do fornecedor local quando o Ollama os devolve.",
  "Family": "Família",
  "Max context": "Contexto máximo",
  "Tool mode": "Modo de ferramentas",
  "Best practices": "Boas práticas",
  "Start a new chat when the previous history no longer adds context.": "Inicie um novo chat quando o histórico anterior já não acrescentar contexto.",
  "Summarize long documents before requesting several tasks on them.": "Resuma documentos longos antes de pedir várias tarefas sobre eles.",
  "Attach only the files and fragments needed for the question.": "Anexe apenas os ficheiros e fragmentos necessários para a pergunta.",
  "Avoid pasting the same content multiple times in the conversation.": "Evite colar o mesmo conteúdo várias vezes na conversa.",
  "More information:": "Mais informações:",
  "and": "e",
  "Turn 0": "Turno 0",
  "Conversation 0": "Conversa 0",
  "Process": "Processo",
  "Warning": "Aviso",
  "Ready. Type your request or attach files.": "Pronto. Escreva o pedido ou anexe ficheiros.",
  "Session ready": "Sessão pronta",
  "Stop": "Parar",
  "Stop current response": "Parar a resposta atual",
  "Send message": "Enviar mensagem",
  "Florentino local": "Florentino local",
  "Start a conversation": "Iniciar uma conversa",
  "Try: \"summarize this project\" or \"list the Python files\".": "Experimente: «resume este projeto» ou «lista os ficheiros Python».",
  "Deciding the next step...": "A decidir o próximo passo...",
  "Reading the attached files...": "A ler os ficheiros anexados...",
  "Extracting information from the PDF...": "A extrair informação do PDF...",
  "Reading the document...": "A ler o documento...",
  "Planning the code change...": "A planear a alteração de código...",
  "Generating code changes...": "A gerar alterações de código...",
  "Looking up current information...": "A procurar informação atualizada...",
  "Checking the result...": "A verificar o resultado...",
  "Preparing the answer...": "A preparar a resposta...",
  "Agents on": "Agentes ativos",
  "Local PDF or text": "PDF ou texto local",
  "Attachments:": "Anexos:",
  "Remove file": "Remover ficheiro",
  "Use": "Usar",
  "Delete": "Eliminar",
  "Download": "Transferir",
  "Installed": "Instalado",
  "(not installed)": "(não instalado)",
  "No saved sessions yet.": "Ainda não há sessões guardadas.",
  "Conversation": "Conversa",
  "Resume": "Retomar",
  "Delete saved conversation": "Eliminar conversa guardada",
  "No projects yet": "Ainda não há projetos",
  "Create one to keep sources and conversations for a subject together.": "Crie um para manter fontes e conversas de um assunto juntas.",
  "Remove": "Remover",
  "Remove source": "Remover fonte",
  "Delete conversation": "Eliminar conversa",
  "No sources yet. Add notes, slides, PDFs or other course material.": "Ainda não há fontes. Adicione apontamentos, slides, PDFs ou outro material.",
  "No sources yet": "Ainda não há fontes",
  "Add notes, slides, PDFs or other course material. Every chat in this project will use them as reference.": "Adicione apontamentos, slides, PDFs ou outro material. Todos os chats deste projeto irão usá-los como referência.",
  "Add first source": "Adicionar primeira fonte",
  "No conversations yet": "Ainda não há conversas",
  "Start a chat and the model will use this project's sources as its reference base.": "Inicie um chat e o modelo usará as fontes deste projeto como base de referência.",
  "Hide sources": "Ocultar fontes",
  "Refreshing": "A atualizar",
  "Deleting...": "A eliminar...",
  "Starting...": "A iniciar...",
  "Downloading": "A transferir",
  "Uninstalling": "A desinstalar",
  "Calculating size...": "A calcular tamanho...",
  "Ollama updated": "Ollama atualizado",
  "Removing local files...": "A remover ficheiros locais...",
  "Could not read the hardware.": "Não foi possível ler o hardware.",
  "Memory is under pressure: closing apps may allow larger models.": "A memória está sob pressão: fechar aplicações pode permitir modelos maiores.",
  "Your machine is ready for compatible local models.": "A sua máquina está pronta para modelos locais compatíveis.",
  "No recommendations available right now.": "Não há recomendações disponíveis neste momento.",
  "Could not load the tools.": "Não foi possível carregar as ferramentas.",
  "API": "API",
  "App": "App",
  "Models": "Modelos",
  "UI error": "Erro de interface",
};

const UI_TRANSLATIONS = {
  es: SPANISH_TRANSLATIONS,
  fr: FRENCH_TRANSLATIONS,
  pt: PORTUGUESE_TRANSLATIONS,
};

const SPANISH_PATTERNS = [
  [/^Turn (.+)$/, "Turno $1"],
  [/^Conversation (.+)$/, "Conversación $1"],
  [/^Tokens for (.+)$/, "Tokens de $1"],
  [/^Answered in (.+)$/, "Respondido en $1"],
  [/^Last turn total = (.+) input \+ (.+) output = (.+) tokens\.$/, "Total del último turno = $1 entrada + $2 salida = $3 tokens."],
  [/^No token data for this turn yet\. It will appear after the model's next response if Ollama returns it\.$/, "Todavía no hay datos de tokens para este turno. Aparecerán después de la próxima respuesta del modelo si Ollama los devuelve."],
  [/^(\d+) source · (.+)$/, "$1 fuente · $2"],
  [/^(\d+) sources? · (\d+) conversations?$/, "$1 fuentes · $2 conversaciones"],
  [/^(\d+) sources? · (.+)$/, "$1 fuentes · $2"],
  [/^(\d+) persistent sources?$/, "$1 fuentes persistentes"],
  [/^(\d+) conversations?$/, "$1 conversaciones"],
  [/^(.+) · added (.+)$/, "$1 · añadido $2"],
  [/^added (.+)$/, "añadido $1"],
  [/^Updated (.+)$/, "Actualizado $1"],
  [/^Internal tag:$/, "Etiqueta interna:"],
  [/^Project: (.+)$/, "Proyecto: $1"],
  [/^RAM approx\. (.+)$/, "RAM aprox. $1"],
  [/^(\d+) tools · (\d+) skills · (\d+) MCP$/, "$1 herramientas · $2 skills · $3 MCP"],
  [/^(\d+) tools$/, "$1 herramientas"],
  [/^(\d+) available$/, "$1 disponibles"],
  [/^(\d+) integrations$/, "$1 integraciones"],
  [/^Ollama ready \((\d+)\)$/, "Ollama listo ($1)"],
  [/^(.+) free$/, "$1 libres"],
  [/^(.+) total$/, "$1 en total"],
  [/^(.+) total in (.+)$/, "$1 en total en $2"],
  [/^(.+) of (.+)$/, "$1 de $2"],
  [/^Safe now · ceiling (.+)$/, "Seguro ahora · límite $1"],
  [/^(.+) cores · (.+)$/, "$1 núcleos · $2"],
];

const FRENCH_PATTERNS = [
  [/^Turn (.+)$/, "Tour $1"],
  [/^Conversation (.+)$/, "Conversation $1"],
  [/^Tokens for (.+)$/, "Tokens pour $1"],
  [/^Answered in (.+)$/, "Répondu en $1"],
  [/^Last turn total = (.+) input \+ (.+) output = (.+) tokens\.$/, "Total du dernier tour = $1 entrée + $2 sortie = $3 tokens."],
  [/^No token data for this turn yet\. It will appear after the model's next response if Ollama returns it\.$/, "Aucune donnée de tokens pour ce tour pour le moment. Elle apparaîtra après la prochaine réponse du modèle si Ollama la renvoie."],
  [/^(\d+) source · (.+)$/, "$1 source · $2"],
  [/^(\d+) sources? · (\d+) conversations?$/, "$1 sources · $2 conversations"],
  [/^(\d+) sources? · (.+)$/, "$1 sources · $2"],
  [/^(\d+) persistent sources?$/, "$1 sources persistantes"],
  [/^(\d+) conversations?$/, "$1 conversations"],
  [/^(.+) · added (.+)$/, "$1 · ajouté $2"],
  [/^added (.+)$/, "ajouté $1"],
  [/^Updated (.+)$/, "Mis à jour $1"],
  [/^Internal tag:$/, "Étiquette interne :"],
  [/^Project: (.+)$/, "Projet : $1"],
  [/^RAM approx\. (.+)$/, "RAM env. $1"],
  [/^(\d+) tools · (\d+) skills · (\d+) MCP$/, "$1 outils · $2 skills · $3 MCP"],
  [/^(\d+) tools$/, "$1 outils"],
  [/^(\d+) available$/, "$1 disponibles"],
  [/^(\d+) integrations$/, "$1 intégrations"],
  [/^Ollama ready \((\d+)\)$/, "Ollama prêt ($1)"],
  [/^(.+) free$/, "$1 libres"],
  [/^(.+) total$/, "$1 au total"],
  [/^(.+) total in (.+)$/, "$1 au total dans $2"],
  [/^(.+) of (.+)$/, "$1 sur $2"],
  [/^Safe now · ceiling (.+)$/, "Sûr maintenant · plafond $1"],
  [/^(.+) cores · (.+)$/, "$1 cœurs · $2"],
];

const PORTUGUESE_PATTERNS = [
  [/^Turn (.+)$/, "Turno $1"],
  [/^Conversation (.+)$/, "Conversa $1"],
  [/^Tokens for (.+)$/, "Tokens de $1"],
  [/^Answered in (.+)$/, "Respondido em $1"],
  [/^Last turn total = (.+) input \+ (.+) output = (.+) tokens\.$/, "Total do último turno = $1 entrada + $2 saída = $3 tokens."],
  [/^No token data for this turn yet\. It will appear after the model's next response if Ollama returns it\.$/, "Ainda não há dados de tokens para este turno. Irão aparecer após a próxima resposta do modelo se o Ollama os devolver."],
  [/^(\d+) source · (.+)$/, "$1 fonte · $2"],
  [/^(\d+) sources? · (\d+) conversations?$/, "$1 fontes · $2 conversas"],
  [/^(\d+) sources? · (.+)$/, "$1 fontes · $2"],
  [/^(\d+) persistent sources?$/, "$1 fontes persistentes"],
  [/^(\d+) conversations?$/, "$1 conversas"],
  [/^(.+) · added (.+)$/, "$1 · adicionado $2"],
  [/^added (.+)$/, "adicionado $1"],
  [/^Updated (.+)$/, "Atualizado $1"],
  [/^Internal tag:$/, "Etiqueta interna:"],
  [/^Project: (.+)$/, "Projeto: $1"],
  [/^RAM approx\. (.+)$/, "RAM aprox. $1"],
  [/^(\d+) tools · (\d+) skills · (\d+) MCP$/, "$1 ferramentas · $2 skills · $3 MCP"],
  [/^(\d+) tools$/, "$1 ferramentas"],
  [/^(\d+) available$/, "$1 disponíveis"],
  [/^(\d+) integrations$/, "$1 integrações"],
  [/^Ollama ready \((\d+)\)$/, "Ollama pronto ($1)"],
  [/^(.+) free$/, "$1 livres"],
  [/^(.+) total$/, "$1 no total"],
  [/^(.+) total in (.+)$/, "$1 no total em $2"],
  [/^(.+) of (.+)$/, "$1 de $2"],
  [/^Safe now · ceiling (.+)$/, "Seguro agora · limite $1"],
  [/^(.+) cores · (.+)$/, "$1 núcleos · $2"],
];

const UI_PATTERNS = {
  es: SPANISH_PATTERNS,
  fr: FRENCH_PATTERNS,
  pt: PORTUGUESE_PATTERNS,
};

function translateText(value) {
  if (currentLanguage === INTERNAL_LANGUAGE) return value;
  const trimmed = String(value).trim();
  if (!trimmed) return value;
  let translated = UI_TRANSLATIONS[currentLanguage]?.[trimmed];
  if (!translated) {
    for (const [pattern, replacement] of UI_PATTERNS[currentLanguage] || []) {
      if (pattern.test(trimmed)) {
        translated = trimmed.replace(pattern, replacement);
        break;
      }
    }
  }
  if (!translated) return value;
  return String(value).replace(trimmed, translated);
}

function isAutoTranslateBlocked(node) {
  if (!node) return false;
  const element = node.nodeType === Node.ELEMENT_NODE ? node : node.parentElement;
  return Boolean(element?.closest?.(NO_AUTO_TRANSLATE_SELECTOR));
}

function translateNode(root) {
  if (!root || isAutoTranslateBlocked(root)) return;
  if (root.nodeType === Node.TEXT_NODE) {
    if (!originalTextNodes.has(root)) originalTextNodes.set(root, root.nodeValue);
    const translated = currentLanguage === INTERNAL_LANGUAGE ? originalTextNodes.get(root) : translateText(originalTextNodes.get(root));
    if (translated !== root.nodeValue) root.nodeValue = translated;
    return;
  }
  if (root.nodeType !== Node.ELEMENT_NODE && root.nodeType !== Node.DOCUMENT_NODE) return;
  if (root.nodeType === Node.ELEMENT_NODE) {
    ["placeholder", "title", "aria-label"].forEach((attribute) => {
      if (root.hasAttribute(attribute)) {
        let sources = originalAttributes.get(root);
        if (!sources) {
          sources = {};
          originalAttributes.set(root, sources);
        }
        if (!Object.prototype.hasOwnProperty.call(sources, attribute)) {
          sources[attribute] = root.getAttribute(attribute);
        }
        const value = sources[attribute];
        const translated = currentLanguage === INTERNAL_LANGUAGE ? value : translateText(value);
        if (translated !== root.getAttribute(attribute)) root.setAttribute(attribute, translated);
      }
    });
  }
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      return isAutoTranslateBlocked(node) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT;
    },
  });
  let textNode = walker.nextNode();
  while (textNode) {
    if (!originalTextNodes.has(textNode)) originalTextNodes.set(textNode, textNode.nodeValue);
    const source = originalTextNodes.get(textNode);
    const translated = currentLanguage === INTERNAL_LANGUAGE ? source : translateText(source);
    if (translated !== textNode.nodeValue) textNode.nodeValue = translated;
    textNode = walker.nextNode();
  }
  if (root.querySelectorAll) {
    root.querySelectorAll("[placeholder], [title], [aria-label]").forEach((element) => {
      if (isAutoTranslateBlocked(element)) return;
      ["placeholder", "title", "aria-label"].forEach((attribute) => {
        if (element.hasAttribute(attribute)) {
          let sources = originalAttributes.get(element);
          if (!sources) {
            sources = {};
            originalAttributes.set(element, sources);
          }
          if (!Object.prototype.hasOwnProperty.call(sources, attribute)) {
            sources[attribute] = element.getAttribute(attribute);
          }
          const value = sources[attribute];
          const translated = currentLanguage === INTERNAL_LANGUAGE ? value : translateText(value);
          if (translated !== element.getAttribute(attribute)) element.setAttribute(attribute, translated);
        }
      });
    });
  }
}

function uiText(value) {
  return translateText(value);
}

function currentLocale() {
  return LANGUAGE_LOCALES[currentLanguage] || LANGUAGE_LOCALES.en;
}

function syncLanguageControl() {
  if (els.languageCurrentLabel) {
    els.languageCurrentLabel.textContent = LANGUAGE_LABELS[currentLanguage] || LANGUAGE_LABELS.en;
  }
  els.languageButtons?.forEach((button) => {
    const active = button.dataset.language === currentLanguage;
    button.classList.toggle("active", active);
    button.setAttribute("aria-checked", String(active));
  });
}

function setDisplayLanguage(language) {
  if (!SUPPORTED_LANGUAGES.includes(language)) return;
  currentLanguage = language;
  localStorage.setItem(LANGUAGE_KEY, currentLanguage);
  syncLanguageControl();
  translateUi();
}

function translateUi() {
  document.documentElement.lang = currentLanguage;
  translateNode(document.body);
  if (!activeChatRequest) renderChatMessages();
  renderAttachments();
  if (state.lastSystemPayload) renderSystem(state.lastSystemPayload);
  renderModels();
  renderProjects();
  renderSessions(state.allSessions);
  renderTokenInfo();
  if (state.lastToolsPayload) renderTools(state.lastToolsPayload);
}

document.documentElement.lang = currentLanguage;

const MODEL_SEARCH_SYNONYMS = {
  coding: ["code", "coder", "program", "programming", "python", "javascript", "development", "software", "debug", "debugging"],
  reasoning: ["reason", "reasoning", "math", "mathematics", "logic", "problems", "think", "analysis", "analyze"],
  general: ["general", "chat", "conversation", "questions", "text", "summary", "summarize", "documents", "pdf", "study", "help"],
  edge: ["fast", "lightweight", "small", "low ram", "local", "laptop", "portable", "edge"],
  workstation: ["powerful", "work", "workstation", "quality", "medium"],
  enterprise: ["large", "maximum", "company", "enterprise", "server"],
};

const els = {
  views: document.querySelectorAll(".view"),
  navButtons: document.querySelectorAll(".nav-button"),
  ollamaStatus: document.querySelector("#ollamaStatus"),
  workspaceLabel: document.querySelector("#workspaceLabel"),
  modelSelect: document.querySelector("#modelSelect"),
  modelSearch: document.querySelector("#modelSearch"),
  modelsList: document.querySelector("#modelsList"),
  sessionsList: document.querySelector("#sessionsList"),
  messages: document.querySelector("#messages"),
  fileInput: document.querySelector("#fileInput"),
  attachmentsList: document.querySelector("#attachmentsList"),
  chatForm: document.querySelector("#chatForm"),
  messageInput: document.querySelector("#messageInput"),
  sendButton: document.querySelector("#sendButton"),
  commandPreview: document.querySelector("#commandPreview"),
  chatTools: document.querySelector(".chat-topbar"),
  toolsPanel: document.querySelector("#toolsPanel"),
  toolsDrawerToggle: document.querySelector("#toolsDrawerToggle"),
  toolsDrawerClose: document.querySelector("#toolsDrawerClose"),
  toolsBackdrop: document.querySelector("#toolsBackdrop"),
  promptActionsMenu: document.querySelector("#promptActionsMenu"),
  agentsMode: document.querySelector("#agentsMode"),
  agentsModeButton: document.querySelector("#agentsModeButton"),
  agentsModeLabel: document.querySelector("#agentsModeLabel"),
  toolsSummary: document.querySelector("#toolsSummary"),
  quickActions: document.querySelector("#quickActions"),
  toolsList: document.querySelector("#toolsList"),
  refreshButton: document.querySelector("#refreshButton"),
  tokenCounter: document.querySelector("#tokenCounter"),
  tokenTurnValue: document.querySelector("#tokenTurnValue"),
  tokenSessionValue: document.querySelector("#tokenSessionValue"),
  tokenInfoTitle: document.querySelector("#tokenInfoTitle"),
  tokenInfoInput: document.querySelector("#tokenInfoInput"),
  tokenInfoOutput: document.querySelector("#tokenInfoOutput"),
  tokenInfoTurn: document.querySelector("#tokenInfoTurn"),
  tokenInfoSession: document.querySelector("#tokenInfoSession"),
  tokenInfoFormula: document.querySelector("#tokenInfoFormula"),
  tokenInfoModel: document.querySelector("#tokenInfoModel"),
  tokenInfoFamily: document.querySelector("#tokenInfoFamily"),
  tokenInfoContext: document.querySelector("#tokenInfoContext"),
  tokenInfoToolMode: document.querySelector("#tokenInfoToolMode"),
  backToChatFromTokens: document.querySelector("#backToChatFromTokens"),
  openChat: document.querySelector("#openChat"),
  newChat: document.querySelector("#newChat"),
  systemSummary: document.querySelector("#systemSummary"),
  ramValue: document.querySelector("#ramValue"),
  ramBar: document.querySelector("#ramBar"),
  ramMeta: document.querySelector("#ramMeta"),
  diskValue: document.querySelector("#diskValue"),
  diskBar: document.querySelector("#diskBar"),
  diskMeta: document.querySelector("#diskMeta"),
  budgetValue: document.querySelector("#budgetValue"),
  budgetBar: document.querySelector("#budgetBar"),
  budgetMeta: document.querySelector("#budgetMeta"),
  modeValue: document.querySelector("#modeValue"),
  modeMeta: document.querySelector("#modeMeta"),
  recommendationsStrip: document.querySelector("#recommendationsStrip"),
  projectsList: document.querySelector("#projectsList"),
  projectCreateForm: document.querySelector("#projectCreateForm"),
  projectNameInput: document.querySelector("#projectNameInput"),
  projectKindInput: document.querySelector("#projectKindInput"),
  paperMetaFields: document.querySelector("#paperMetaFields"),
  paperTitleInput: document.querySelector("#paperTitleInput"),
  paperFieldInput: document.querySelector("#paperFieldInput"),
  paperVenueInput: document.querySelector("#paperVenueInput"),
  paperTypeInput: document.querySelector("#paperTypeInput"),
  projectSelect: document.querySelector("#projectSelect"),
  researcherSelect: document.querySelector("#researcherSelect"),
  openResearcherProfile: document.querySelector("#openResearcherProfile"),
  researcherView: document.querySelector("#researcherView"),
  researcherForm: document.querySelector("#researcherForm"),
  researcherFormTitle: document.querySelector("#researcherFormTitle"),
  researcherName: document.querySelector("#researcherName"),
  researcherEmail: document.querySelector("#researcherEmail"),
  researcherFields: document.querySelector("#researcherFields"),
  researcherVenues: document.querySelector("#researcherVenues"),
  researcherStyle: document.querySelector("#researcherStyle"),
  researcherGuidelines: document.querySelector("#researcherGuidelines"),
  researcherLensGrid: document.querySelector("#researcherLensGrid"),
  deleteResearcher: document.querySelector("#deleteResearcher"),
  cancelResearcher: document.querySelector("#cancelResearcher"),
  projectContextBar: document.querySelector("#projectContextBar"),
  projectContextName: document.querySelector("#projectContextName"),
  projectContextMeta: document.querySelector("#projectContextMeta"),
  projectSourceInput: document.querySelector("#projectSourceInput"),
  projectSourcesList: document.querySelector("#projectSourcesList"),
  toggleProjectSources: document.querySelector("#toggleProjectSources"),
  openProjects: document.querySelector("#openProjects"),
  showProjectCreate: document.querySelector("#showProjectCreate"),
  cancelProjectCreate: document.querySelector("#cancelProjectCreate"),
  backToProjects: document.querySelector("#backToProjects"),
  projectDetailName: document.querySelector("#projectDetailName"),
  projectDetailMeta: document.querySelector("#projectDetailMeta"),
  projectDetailSources: document.querySelector("#projectDetailSources"),
  projectDetailSourceInput: document.querySelector("#projectDetailSourceInput"),
  projectChatsList: document.querySelector("#projectChatsList"),
  newProjectChat: document.querySelector("#newProjectChat"),
  languageControl: document.querySelector("#languageControl"),
  languageTrigger: document.querySelector(".language-trigger"),
  languageCurrentLabel: document.querySelector("#languageCurrentLabel"),
  languageButtons: document.querySelectorAll("[data-language]"),
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  return response.json();
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function formatDate(value) {
  if (!value || value === "?") return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value.slice(0, 19);
  return new Intl.DateTimeFormat(currentLocale(), {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function formatGb(value) {
  const number = Number(value || 0);
  return `${number.toFixed(number >= 10 ? 0 : 1)} GB`;
}

function formatBytes(value) {
  const number = Number(value || 0);
  if (number <= 0) return "0 MB";
  const gb = number / 1024 / 1024 / 1024;
  if (gb >= 1) return `${gb.toFixed(gb >= 10 ? 0 : 1)} GB`;
  return `${(number / 1024 / 1024).toFixed(0)} MB`;
}

function emptyTokenUsage() {
  return {
    last_call: null,
    last_turn: {
      prompt_tokens: 0,
      completion_tokens: 0,
      total_tokens: 0,
      model: "",
      available: false,
    },
    session_total: {
      prompt_tokens: 0,
      completion_tokens: 0,
      total_tokens: 0,
      model: "",
      available: false,
    },
    calls: [],
  };
}

function normalizeTokenUsage(usage) {
  const base = emptyTokenUsage();
  if (!usage || typeof usage !== "object") return base;
  const normalize = (part) => ({
    ...base.last_turn,
    ...(part && typeof part === "object" ? part : {}),
    prompt_tokens: Number(part?.prompt_tokens || 0),
    completion_tokens: Number(part?.completion_tokens || 0),
    total_tokens: Number(part?.total_tokens || 0),
    available: Boolean(part?.available) || Number(part?.total_tokens || 0) > 0,
  });
  return {
    last_call: usage.last_call ? normalize(usage.last_call) : null,
    last_turn: normalize(usage.last_turn),
    session_total: normalize(usage.session_total),
    calls: Array.isArray(usage.calls) ? usage.calls.map(normalize) : [],
  };
}

function formatTokenCompact(value) {
  const number = Number(value || 0);
  if (number >= 1000000) return `${(number / 1000000).toFixed(1)}M`;
  if (number >= 1000) return `${(number / 1000).toFixed(1)}k`;
  return String(number);
}

function formatTokenExact(value) {
  return new Intl.NumberFormat(currentLocale()).format(Number(value || 0));
}

function clampPercent(value) {
  return Math.max(0, Math.min(100, Number(value || 0)));
}

function setMeter(node, percent) {
  node.style.width = `${clampPercent(percent)}%`;
}

function persistUiState() {
  const payload = {
    currentSession: state.currentSession,
    chatMessages: state.chatMessages,
    uploadedFiles: state.uploadedFiles,
    activeView: state.activeView,
    tokenUsage: state.tokenUsage,
    agentsMode: Boolean(els.agentsMode?.checked),
    selectedModel: els.modelSelect?.value || "",
    currentProject: state.currentProject,
    currentResearcher: state.currentResearcher,
  };
  localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
}

function restoreUiState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return;
    const payload = JSON.parse(raw);
    state.currentSession = payload.currentSession || null;
    state.chatMessages = Array.isArray(payload.chatMessages) ? payload.chatMessages : [];
    state.uploadedFiles = Array.isArray(payload.uploadedFiles) ? payload.uploadedFiles : [];
    state.tokenUsage = normalizeTokenUsage(payload.tokenUsage);
    state.agentsMode = Boolean(payload.agentsMode);
    state.currentProject = payload.currentProject || null;
    state.currentResearcher = payload.currentResearcher || null;
    state.activeView = [
      "homeView",
      "projectsView",
      "projectDetailView",
      "researcherView",
      "chatView",
      "tokenInfoView",
    ].includes(payload.activeView)
      ? payload.activeView
      : "homeView";
    if (payload.selectedModel) {
      els.modelSelect.dataset.pendingValue = payload.selectedModel;
    }
  } catch {
    state.currentSession = null;
    state.chatMessages = [];
    state.uploadedFiles = [];
    state.tokenUsage = emptyTokenUsage();
    state.agentsMode = false;
    state.currentProject = null;
    state.currentResearcher = null;
    state.activeView = "homeView";
  }
}

function setToolsDrawer(open) {
  if (!els.toolsPanel) return;
  els.toolsPanel.classList.toggle("open", open);
  els.toolsPanel.setAttribute("aria-hidden", String(!open));
  if (els.toolsBackdrop) els.toolsBackdrop.hidden = !open;
  els.toolsDrawerToggle?.setAttribute("aria-expanded", String(open));
}

function toggleToolsDrawer() {
  setToolsDrawer(!els.toolsPanel?.classList.contains("open"));
}

function switchView(viewId, scrollTarget = null) {
  if (viewId !== "chatView") setToolsDrawer(false);
  state.activeView = viewId;
  document.body.classList.toggle("chat-view-active", viewId === "chatView");
  document.body.classList.toggle("token-info-view-active", viewId === "tokenInfoView");
  document.body.classList.toggle("researcher-view-active", viewId === "researcherView");
  document.body.classList.toggle(
    "projects-view-active",
    viewId === "projectsView" || viewId === "projectDetailView",
  );
  els.views.forEach((view) => {
    const active = view.id === viewId;
    view.hidden = !active;
    view.classList.toggle("active-view", active);
  });

  els.navButtons.forEach((button) => {
    const projectsArea = viewId === "projectsView" || viewId === "projectDetailView";
    const active = (
      button.dataset.view === viewId
      || (projectsArea && button.id === "openProjects")
    ) && !button.dataset.scroll;
    button.classList.toggle("active", active);
  });

  if (scrollTarget) {
    persistUiState();
    window.setTimeout(() => {
      document.getElementById(scrollTarget)?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 40);
    return;
  }
  persistUiState();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function currentModelInfo() {
  const selected = els.modelSelect?.value || "";
  return state.models.find((model) => (
    model.id === selected || model.ollama_tag === selected
  )) || null;
}

function applyTokenUsage(usage) {
  state.tokenUsage = normalizeTokenUsage(usage);
  updateTokenDisplay();
  renderTokenInfo();
  persistUiState();
}

function updateTokenDisplay() {
  const usage = normalizeTokenUsage(state.tokenUsage);
  state.tokenUsage = usage;
  const turn = usage.last_turn;
  const session = usage.session_total;
  if (els.tokenTurnValue) {
    setRollingText(els.tokenTurnValue, `Turn ${formatTokenCompact(turn.total_tokens)}`);
  }
  if (els.tokenSessionValue) {
    setRollingText(els.tokenSessionValue, `Conversation ${formatTokenCompact(session.total_tokens)}`);
  }
}

function setRollingText(node, value) {
  if (!node || node.textContent === value) return;
  node.textContent = value;
  node.classList.remove("token-roll");
  void node.offsetWidth;
  node.classList.add("token-roll");
}

function renderTokenInfo() {
  if (!els.tokenInfoTitle) return;
  const usage = normalizeTokenUsage(state.tokenUsage);
  const turn = usage.last_turn;
  const session = usage.session_total;
  const model = currentModelInfo();
  const modelName = model?.display_name || usage.session_total.model || els.modelSelect?.value || "Local model";
  els.tokenInfoTitle.textContent = `Tokens for ${modelName}`;
  els.tokenInfoInput.textContent = formatTokenExact(turn.prompt_tokens);
  els.tokenInfoOutput.textContent = formatTokenExact(turn.completion_tokens);
  els.tokenInfoTurn.textContent = formatTokenExact(turn.total_tokens);
  els.tokenInfoSession.textContent = formatTokenExact(session.total_tokens);
  els.tokenInfoFormula.textContent = uiText(turn.available
    ? `Last turn total = ${formatTokenExact(turn.prompt_tokens)} input + ${formatTokenExact(turn.completion_tokens)} output = ${formatTokenExact(turn.total_tokens)} tokens.`
    : "No token data for this turn yet. It will appear after the model's next response if Ollama returns it.");
  els.tokenInfoModel.textContent = model
    ? `${model.display_name} (${model.ollama_tag})`
    : (usage.session_total.model || els.modelSelect?.value || "--");
  els.tokenInfoFamily.textContent = model?.family || "--";
  els.tokenInfoContext.textContent = model?.context_length
    ? uiText(`${formatTokenExact(model.context_length)} tokens`)
    : "--";
  els.tokenInfoToolMode.textContent = model?.tool_mode || "--";
}

function renderChatMessages() {
  els.messages.innerHTML = "";
  if (!state.chatMessages.length) {
    setEmptyChat();
    return;
  }
  state.chatMessages.forEach((message) => {
    appendMessageNode(
      message.role,
      message.text,
      message.extraClass || "",
      { duration_ms: message.duration_ms, process_log: message.process_log },
    );
  });
}

function appendMessageNode(role, text, extraClass = "", meta = {}) {
  const empty = els.messages.querySelector(".empty-state");
  if (empty) empty.remove();
  const node = document.createElement("div");
  node.className = `message ${role} ${extraClass}`.trim();
  if (extraClass.includes("session-info")) {
    appendSessionInfo(node, text);
  } else {
    const body = document.createElement("div");
    body.textContent = extraClass.includes("error") || extraClass.includes("stopped") ? uiText(text) : text;
    node.appendChild(body);
  }
  if (meta.duration_ms) {
    const detail = document.createElement("small");
    detail.className = "message-meta";
    detail.textContent = uiText(`Answered in ${formatElapsed(meta.duration_ms)}`);
    node.appendChild(detail);
  }
  if (Array.isArray(meta.process_log) && meta.process_log.length) {
    appendProcessLog(node, meta.process_log);
  }
  els.messages.appendChild(node);
  els.messages.scrollTop = els.messages.scrollHeight;
  return node;
}

function appendProcessLog(node, entries = [], label = "Process") {
  const cleanEntries = entries
    .map((entry) => String(entry || "").trim())
    .filter(Boolean);
  if (!cleanEntries.length) return null;
  const details = document.createElement("details");
  details.className = "process-log";
  const summary = document.createElement("summary");
  summary.textContent = uiText(label);
  details.appendChild(summary);
  const list = document.createElement("ol");
  cleanEntries.forEach((entry) => {
    const item = document.createElement("li");
    item.textContent = uiText(entry);
    list.appendChild(item);
  });
  details.appendChild(list);
  node.appendChild(details);
  return details;
}

function appendSessionInfo(node, text) {
  const lines = String(text || "").split(/\n+/).map((line) => line.trim()).filter(Boolean);
  const entries = [];
  const notes = [];
  lines.slice(1).forEach((line) => {
    const separator = line.indexOf(":");
    if (separator > 0) {
      entries.push({
        key: line.slice(0, separator).trim(),
        value: line.slice(separator + 1).trim(),
      });
    } else {
      notes.push(line);
    }
  });

  const details = document.createElement("details");
  details.className = "session-details";
  const summary = document.createElement("summary");
  const title = document.createElement("span");
  title.textContent = uiText("Session ready");
  const mode = entries.find((entry) => entry.key.toLowerCase() === "mode")?.value || "classic chat";
  const model = entries.find((entry) => entry.key.toLowerCase() === "model")?.value || "local model";
  const meta = document.createElement("small");
  meta.textContent = uiText(`${model} · ${mode}`);
  summary.append(title, meta);
  details.appendChild(summary);

  const list = document.createElement("dl");
  list.className = "session-facts";
  entries.forEach((entry) => {
    const wrapper = document.createElement("div");
    const term = document.createElement("dt");
    const description = document.createElement("dd");
    term.textContent = uiText(entry.key);
    description.textContent = uiText(entry.value);
    wrapper.append(term, description);
    list.appendChild(wrapper);
  });
  details.appendChild(list);

  if (notes.length) {
    const note = document.createElement("p");
    note.className = "session-note";
    note.textContent = uiText(notes.join(" "));
    details.appendChild(note);
  }

  node.appendChild(details);
}

function addMessage(role, text, extraClass = "", meta = {}) {
  state.chatMessages.push({ role, text, extraClass, ...meta });
  appendMessageNode(role, text, extraClass, meta);
  persistUiState();
}

function buildProgressMessages(prompt = "", files = []) {
  const text = `${prompt} ${files.map((file) => file.name || file.path || "").join(" ")}`.toLowerCase();
  const messages = ["Deciding the next step..."];
  if (files.length) {
    messages.push("Reading the attached files...");
  }
  if (/\bpdf\b|\.pdf\b/.test(text)) {
    messages.push("Extracting information from the PDF...");
  } else if (/\bdocx?\b|\.docx?\b|document|file/.test(text)) {
    messages.push("Reading the document...");
  }
  if (/\b(code|test|bug|fix|implement|generate|generating|create|write)\b/.test(text)) {
    messages.push("Planning the code change...");
    messages.push("Generating code changes...");
  }
  if (/web|internet|latest|current|today|online/.test(text)) {
    messages.push("Looking up current information...");
  }
  messages.push("Checking the result...");
  messages.push("Preparing the answer...");
  return [...new Set(messages)];
}

function addThinkingMessage(prompt = "", files = []) {
  const empty = els.messages.querySelector(".empty-state");
  if (empty) empty.remove();
  const node = document.createElement("div");
  node.className = "message assistant thinking";
  const startedAt = Date.now();
  const progressMessages = buildProgressMessages(prompt, files);
  const processEntries = [progressMessages[0]];
  node.innerHTML = `
    <div class="thinking-main">
      <span class="thinking-loader" aria-hidden="true"></span>
      <span class="thinking-copy">
        <span class="thinking-status">${escapeHtml(uiText(progressMessages[0]))}</span>
        <small class="thinking-time">0.0s</small>
      </span>
    </div>
    <details class="process-log thinking-process">
      <summary>${escapeHtml(uiText("Process"))}</summary>
      <ol>
        <li>${escapeHtml(uiText(progressMessages[0]))}</li>
      </ol>
    </details>
  `;
  const status = node.querySelector(".thinking-status");
  const timer = node.querySelector(".thinking-time");
  const processList = node.querySelector(".thinking-process ol");
  const addProcessEntry = (entry) => {
    const clean = String(entry || "").trim();
    if (!clean || processEntries.includes(clean)) return;
    processEntries.push(clean);
    const item = document.createElement("li");
    item.textContent = uiText(clean);
    processList?.appendChild(item);
  };
  node._startedAt = startedAt;
  node._progressIndex = 0;
  node._processEntries = processEntries;
  node._addProcessEntry = addProcessEntry;
  node._timerId = window.setInterval(() => {
    if (timer) timer.textContent = formatElapsed(Date.now() - startedAt);
  }, 100);
  node._progressTimerId = window.setInterval(() => {
    if (!status || progressMessages.length <= 1) return;
    node._progressIndex = Math.min(node._progressIndex + 1, progressMessages.length - 1);
    status.textContent = uiText(progressMessages[node._progressIndex]);
    addProcessEntry(progressMessages[node._progressIndex]);
  }, 3500);
  els.messages.appendChild(node);
  els.messages.scrollTop = els.messages.scrollHeight;
  return node;
}

function removeThinkingMessage(node) {
  if (node?._timerId) {
    window.clearInterval(node._timerId);
  }
  if (node?._progressTimerId) {
    window.clearInterval(node._progressTimerId);
  }
  if (node && node.parentNode) {
    node.remove();
  }
}

function formatElapsed(ms) {
  const seconds = Math.max(0, ms) / 1000;
  if (seconds < 60) {
    return `${seconds.toFixed(1)}s`;
  }
  const wholeSeconds = Math.round(seconds);
  const minutes = Math.floor(wholeSeconds / 60);
  const remainder = wholeSeconds % 60;
  return `${minutes}m ${String(remainder).padStart(2, "0")}s`;
}

function setChatRequestRunning(running) {
  els.sendButton.disabled = false;
  els.sendButton.textContent = uiText(running ? "Stop" : "Send");
  els.sendButton.classList.toggle("stop-button", Boolean(running));
  els.sendButton.setAttribute("aria-label", uiText(running ? "Stop current response" : "Send message"));
}

function createRequestId() {
  if (window.crypto?.randomUUID) {
    return window.crypto.randomUUID();
  }
  return `chat_${Date.now()}_${Math.random().toString(16).slice(2)}`;
}

function stopActiveChatRequest() {
  if (!activeChatRequest) return;
  const { controller, requestId } = activeChatRequest;
  api("/api/chat/cancel", {
    method: "POST",
    body: JSON.stringify({ request_id: requestId }),
  }).catch(() => {});
  controller.abort();
}

function setEmptyChat() {
  els.messages.innerHTML = `
    <div class="empty-state">
      <div>
        <p class="eyebrow">${escapeHtml(uiText("Florentino local"))}</p>
        <h3>${escapeHtml(uiText("Start a conversation"))}</h3>
        <p>${escapeHtml(uiText("Try: \"summarize this project\" or \"list the Python files\"."))}</p>
      </div>
    </div>
  `;
}

function buildSessionInfoMessage(payload) {
  const warnings = Array.isArray(payload.warnings) && payload.warnings.length
    ? `\nWarning: ${payload.warnings.join(" ")}`
    : "";
  return [
    "ci2lab UI",
    `Model: ${payload.model || payload.display_name || "?"}`,
    `Tool mode: ${payload.tool_mode || "?"}`,
    `CWD: ${payload.cwd || "?"}`,
    `Session: ${payload.session_id || "?"}`,
    `Project: ${payload.project_name || "Outside projects"}`,
    `Mode: ${payload.multi_agent ? "agents" : "classic chat"}`,
    `Security: ${payload.security_profile || "standard"} / ${payload.security_engine || "ci2lab"}`,
    "",
    "Ready. Type your request or attach files.",
  ].join("\n") + warnings;
}

async function startChatSession({ forceNew = false } = {}) {
  if (!forceNew && state.currentSession && state.chatMessages.length) return;
  setEmptyChat();
  const result = await api("/api/chat/start", {
    method: "POST",
    body: JSON.stringify({
      model: els.modelSelect.value,
      multi_agent: Boolean(els.agentsMode?.checked),
      project_id: state.currentProject,
      researcher_id: state.currentResearcher,
    }),
  });
  if (!result.ok) {
    addMessage("assistant", result.error || "Could not start the local chat.", "error");
    return;
  }

  state.currentSession = result.session_id;
  state.chatMessages = [];
  applyTokenUsage(result.usage);
  addMessage("assistant", buildSessionInfoMessage(result), "session-info");
}

function updateCommandPreview() {
  const model = els.modelSelect.value || "<model>";
  if (els.commandPreview) {
    const agentsFlag = els.agentsMode?.checked ? " --multi-agent" : "";
    els.commandPreview.textContent = `ci2lab --model ${model}${agentsFlag} chat`;
  }
}

function updateAgentsModeState({ persist = true } = {}) {
  const active = Boolean(els.agentsMode?.checked);
  els.chatTools?.classList.toggle("agents-active", active);
  els.agentsModeButton?.classList.toggle("active", active);
  els.agentsModeButton?.setAttribute("aria-pressed", String(active));
  if (els.agentsModeLabel) {
    els.agentsModeLabel.textContent = uiText(active ? "Agents on" : "Agents");
  }
  updateCommandPreview();
  if (persist) persistUiState();
}

function toggleAgentsMode() {
  if (!els.agentsMode) return;
  els.agentsMode.checked = !els.agentsMode.checked;
  updateAgentsModeState();
}

function renderAttachments() {
  if (!els.attachmentsList) return;
  if (!state.uploadedFiles.length) {
    els.attachmentsList.innerHTML = `<span class="attachment-empty">${escapeHtml(uiText("Local PDF or text"))}</span>`;
    return;
  }
  els.attachmentsList.innerHTML = state.uploadedFiles.map((file) => `
    <span class="attachment-chip">
      <span>${escapeHtml(file.name)}</span>
      <small>${escapeHtml(file.size_label || "")}</small>
      <button type="button" data-remove-attachment="${escapeHtml(file.path)}" title="${escapeHtml(uiText("Remove file"))}">×</button>
    </span>
  `).join("");
}

function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(reader.error || new Error("Could not read the file."));
    reader.readAsDataURL(file);
  });
}

async function uploadSelectedFiles(event) {
  const files = Array.from(event.target.files || []);
  if (!files.length) return;
  if (state.currentProject) {
    const forwardedEvent = { target: { files, value: "", disabled: false } };
    await uploadProjectSources(forwardedEvent);
    event.target.value = "";
    return;
  }
  els.fileInput.disabled = true;
  for (const file of files) {
    try {
      const content = await readFileAsDataUrl(file);
      const result = await api("/api/files/upload", {
        method: "POST",
        body: JSON.stringify({
          name: file.name,
          size: file.size,
          content_base64: content,
        }),
      });
      if (result.ok && result.file) {
        state.uploadedFiles.push(result.file);
        renderAttachments();
        persistUiState();
      } else {
        addMessage("assistant", result.error || `Could not upload ${file.name}`, "error");
      }
    } catch (error) {
      addMessage("assistant", error.message || `Could not upload ${file.name}`, "error");
    }
  }
  els.fileInput.value = "";
  els.fileInput.disabled = false;
}

function removeAttachment(path) {
  state.uploadedFiles = state.uploadedFiles.filter((file) => file.path !== path);
  renderAttachments();
  persistUiState();
}

function buildDisplayMessage(message, files) {
  const base = message || "Read and summarize the attached files.";
  if (!files.length) return base;
  const list = files.map((file) => `- ${file.name}`).join("\n");
  return `${base}\n\nAttachments:\n${list}`;
}

function normalizeSearchText(value) {
  return String(value || "")
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "");
}

function searchTerms(query) {
  const normalized = normalizeSearchText(query).trim();
  if (!normalized) return [];
  const terms = new Set(normalized.split(/\s+/).filter(Boolean));
  Object.entries(MODEL_SEARCH_SYNONYMS).forEach(([category, synonyms]) => {
    const allWords = [category, ...synonyms].map(normalizeSearchText);
    if (allWords.some((word) => normalized.includes(word))) {
      terms.add(category);
      allWords.forEach((word) => terms.add(word));
    }
  });
  return [...terms];
}

function modelSearchHaystack(model) {
  const categories = model.categories || [];
  const synonymWords = categories.flatMap((category) => MODEL_SEARCH_SYNONYMS[category] || []);
  const benchmarkUses = Object.entries(model.benchmark_score || {})
    .filter(([, score]) => Number(score) >= 0.7)
    .map(([use]) => use);
  return normalizeSearchText([
    model.display_name,
    model.id,
    model.ollama_tag,
    model.family,
    model.tier,
    model.fit_label,
    ...categories,
    ...benchmarkUses,
    ...synonymWords,
  ].join(" "));
}

function orderedModels() {
  const installed = state.models.filter((model) => model.installed);
  const pending = state.models.filter((model) => !model.installed);
  return [...installed, ...pending];
}

function renderModelProgress(model) {
  const deleteTask = state.deleteTasks[model.ollama_tag];
  if (deleteTask) return renderTaskProgress(deleteTask, "delete");

  const task = state.pullTasks[model.ollama_tag];
  if (!task) return "";
  return renderTaskProgress(task, "pull");
}

function renderTaskProgress(task, type) {
  if (!task) return "";
  const percent = clampPercent(task.percent || 0);
  const visiblePercent = task.done ? percent : Math.max(percent, task.total ? 3 : 8);
  const status = task.error || task.status || (type === "delete" ? "Uninstalling" : "Downloading");
  const detail = type === "pull"
    ? (task.total ? `${formatBytes(task.completed)} of ${formatBytes(task.total)}` : "Calculating size...")
    : (task.done ? "Ollama updated" : "Removing local files...");
  const className = `${type} ${task.error ? "error" : task.done ? "done" : "active"}`;
  const busyLoader = !task.done && !task.error
    ? `<span class="tiny-loader" aria-hidden="true"></span>`
    : "";

  return `
    <div class="download-progress ${className}">
      <div class="progress-row">
        <span>${escapeHtml(uiText(status))}</span>
        <strong class="progress-value">${busyLoader}${percent.toFixed(0)}%</strong>
      </div>
      <div class="progress-bar"><i style="width: ${visiblePercent}%"></i></div>
      <small>${escapeHtml(uiText(detail))}</small>
    </div>
  `;
}

function renderModelActions(model) {
  const buttons = [
    `<button type="button" data-action="use" data-model="${escapeHtml(model.id)}">${escapeHtml(uiText("Use"))}</button>`,
  ];
  if (model.installed) {
    buttons.push(
      `<button class="danger-button" type="button" data-action="delete" data-tag="${escapeHtml(model.ollama_tag)}">${escapeHtml(uiText("Delete"))}</button>`,
    );
  } else {
    buttons.push(
      `<button type="button" data-action="pull" data-tag="${escapeHtml(model.ollama_tag)}">${escapeHtml(uiText("Download"))}</button>`,
    );
  }
  return `<div class="model-actions">${buttons.join("")}</div>`;
}

function renderModels() {
  const terms = searchTerms(els.modelSearch.value);
  const models = orderedModels().filter((model) => {
    const haystack = modelSearchHaystack(model);
    return !terms.length || terms.some((term) => haystack.includes(term));
  });

  els.modelsList.innerHTML = models.map((model) => `
    <article class="model-card">
      <header>
        <div>
          <h4>${escapeHtml(model.display_name)}</h4>
          <div class="meta">${escapeHtml(model.id)} · ${escapeHtml(model.ollama_tag)}</div>
        </div>
        <span class="badge ${model.installed ? "ok" : ""}">${escapeHtml(model.installed ? uiText("Installed") : model.tier)}</span>
      </header>
      <div class="meta">
        ${escapeHtml(model.categories.join(", "))} · ${escapeHtml(uiText(`RAM approx. ${model.ram_inference_gb} GB`))}
        ${model.fit_label ? ` · ${escapeHtml(model.fit_label)}` : ""}
      </div>
      ${renderModelActions(model)}
      ${renderModelProgress(model)}
    </article>
  `).join("");
}

function renderModelSelect() {
  const current = els.modelSelect.dataset.pendingValue || els.modelSelect.value;
  const models = orderedModels();
  els.modelSelect.innerHTML = models.map((model) => `
    <option value="${escapeHtml(model.id)}">${escapeHtml(model.display_name)} ${model.installed ? "" : uiText("(not installed)")}</option>
  `).join("");

  const currentModel = models.find((model) => model.id === current || model.ollama_tag === current);
  const firstInstalled = models.find((model) => model.installed);
  const fallback = firstInstalled || models[0];
  if (currentModel?.installed) {
    els.modelSelect.value = currentModel.id;
    delete els.modelSelect.dataset.pendingValue;
  } else if (fallback) {
    els.modelSelect.value = fallback.id;
    delete els.modelSelect.dataset.pendingValue;
  } else {
    delete els.modelSelect.dataset.pendingValue;
  }
  updateCommandPreview();
  persistUiState();
}

function renderSessions(sessions) {
  if (!sessions.length) {
    els.sessionsList.innerHTML = `<p class="meta">${escapeHtml(uiText("No saved sessions yet."))}</p>`;
    return;
  }
  els.sessionsList.innerHTML = sessions.map((session) => {
    const project = state.projects.find((item) => item.id === session.project_id);
    const scope = project ? `Project: ${project.name}` : "Outside projects";
    return `
    <article class="session-card">
      <h4>${escapeHtml(session.title || uiText("Conversation"))}</h4>
      <div class="session-tag">${escapeHtml(uiText("Internal tag:"))} <code>${escapeHtml(session.internal_tag || session.id)}</code></div>
      <div class="session-tag">${escapeHtml(uiText(scope))}</div>
      <div class="meta">${escapeHtml(session.model)} · ${escapeHtml(formatDate(session.updated_at))}</div>
      <div class="meta">${escapeHtml(session.cwd)}</div>
      <div class="session-actions">
        <button type="button" data-session="${escapeHtml(session.id)}">${escapeHtml(uiText("Resume"))}</button>
        <button
          class="danger-button"
          type="button"
          data-delete-session="${escapeHtml(session.id)}"
          title="${escapeHtml(uiText("Delete saved conversation"))}"
        >${escapeHtml(uiText("Delete"))}</button>
      </div>
    </article>
  `;
  }).join("");
}

function currentProjectInfo() {
  return state.projects.find((project) => project.id === state.currentProject) || null;
}

function renderProjects() {
  if (!els.projectsList) return;
  if (!state.projects.length) {
    els.projectsList.innerHTML = `
      <div class="project-empty">
        <strong>${escapeHtml(uiText("No projects yet"))}</strong>
        <p>${escapeHtml(uiText("Create one to keep sources and conversations for a subject together."))}</p>
      </div>
    `;
  } else {
    els.projectsList.innerHTML = state.projects.map((project) => `
      <article
        class="project-card ${project.id === state.currentProject ? "active" : ""}"
        data-open-project="${escapeHtml(project.id)}"
        tabindex="0"
      >
        <div class="project-card-folder" aria-hidden="true">▱</div>
        <div class="project-card-copy">
          <h4>${escapeHtml(project.name)}</h4>
          <p>${escapeHtml(uiText(`${project.source_count} source${project.source_count === 1 ? "" : "s"} · ${project.source_size_label}`))}</p>
          <small>${escapeHtml(uiText(`Updated ${formatDate(project.updated_at)}`))}</small>
        </div>
        <div class="project-card-actions">
          <button class="danger-button" type="button" data-delete-project="${escapeHtml(project.id)}">${escapeHtml(uiText("Delete"))}</button>
          <span class="project-open-arrow" aria-hidden="true">›</span>
        </div>
      </article>
    `).join("");
  }

  if (els.projectSelect) {
    els.projectSelect.innerHTML = [
      `<option value="">${escapeHtml(uiText("Outside projects"))}</option>`,
      ...state.projects.map((project) => (
        `<option value="${escapeHtml(project.id)}">${escapeHtml(project.name)}</option>`
      )),
    ].join("");
    els.projectSelect.value = currentProjectInfo() ? state.currentProject : "";
  }
  renderProjectContext();
  if (state.activeView === "projectDetailView") renderProjectDetail();
}

async function loadProjectSources() {
  if (!state.currentProject) {
    state.projectSources = [];
    renderProjectContext();
    return;
  }
  const result = await api(`/api/projects/${encodeURIComponent(state.currentProject)}/sources`);
  state.projectSources = result.ok ? (result.sources || []) : [];
  renderProjectContext();
}

function renderProjectContext() {
  const project = currentProjectInfo();
  if (!els.projectContextBar) return;
  els.projectContextBar.hidden = !project;
  if (!project) {
    state.projectSources = [];
    if (els.projectSourcesList) els.projectSourcesList.hidden = true;
    return;
  }
  els.projectContextName.textContent = project.name;
  const sourcesLabel = uiText(`${project.source_count} persistent source${project.source_count === 1 ? "" : "s"}`);
  if (project.kind === "paper_review") {
    const bits = [project.field, project.target_venue].filter(Boolean).join(" · ");
    els.projectContextMeta.textContent =
      uiText("Grounded peer-review mode") + (bits ? ` — ${bits}` : "") + ` · ${sourcesLabel}`;
  } else {
    els.projectContextMeta.textContent = sourcesLabel;
  }
  if (!els.projectSourcesList) return;
  els.projectSourcesList.innerHTML = state.projectSources.length
    ? state.projectSources.map((source) => `
        <div class="project-source-row">
          <span><strong>${escapeHtml(source.name)}</strong><small>${escapeHtml(source.size_label)}</small></span>
          <button type="button" data-delete-source="${escapeHtml(source.id)}">${escapeHtml(uiText("Remove"))}</button>
        </div>
      `).join("")
    : `<p class="meta">${escapeHtml(uiText("No sources yet. Add notes, slides, PDFs or other course material."))}</p>`;
}

function projectSessions(projectId = state.currentProject) {
  return state.allSessions.filter((session) => session.project_id === projectId);
}

function renderProjectDetail() {
  const project = currentProjectInfo();
  if (!project) {
    if (state.activeView === "projectDetailView") switchView("projectsView");
    return;
  }
  const conversations = projectSessions(project.id);
  els.projectDetailName.textContent = project.name;
  els.projectDetailMeta.textContent = uiText(
    `${project.source_count} source${project.source_count === 1 ? "" : "s"}`
    + ` · ${conversations.length} conversation${conversations.length === 1 ? "" : "s"}`
  );

  els.projectDetailSources.innerHTML = state.projectSources.length
    ? state.projectSources.map((source) => `
        <article class="project-source-card">
          <div class="source-file-icon" aria-hidden="true">▤</div>
          <div class="source-file-copy">
            <strong>${escapeHtml(source.name)}</strong>
            <span>${escapeHtml(uiText(`${source.size_label} · added ${formatDate(source.created_at)}`))}</span>
          </div>
          <button
            class="source-remove-button"
            type="button"
            data-delete-source="${escapeHtml(source.id)}"
            title="${escapeHtml(uiText("Remove source"))}"
            aria-label="${escapeHtml(uiText(`Remove ${source.name}`))}"
          >×</button>
        </article>
      `).join("")
    : `
      <div class="project-detail-empty">
        <div class="empty-folder-icon" aria-hidden="true">▱</div>
        <strong>${escapeHtml(uiText("No sources yet"))}</strong>
        <p>${escapeHtml(uiText("Add notes, slides, PDFs or other course material. Every chat in this project will use them as reference."))}</p>
        <label class="source-add-button inline-source-add" for="projectDetailSourceInput">
          <span aria-hidden="true">＋</span> ${escapeHtml(uiText("Add first source"))}
        </label>
      </div>
    `;

  els.projectChatsList.innerHTML = conversations.length
    ? conversations.map((session) => `
        <article class="project-chat-row">
          <button
            class="project-chat-open"
            type="button"
            data-project-session="${escapeHtml(session.id)}"
          >
            <span class="project-chat-icon" aria-hidden="true">◯</span>
            <span>
              <strong>${escapeHtml(session.title || uiText("Conversation"))}</strong>
              <small>${escapeHtml(formatDate(session.updated_at))} · ${escapeHtml(session.model)}</small>
            </span>
            <span class="project-chat-arrow" aria-hidden="true">›</span>
          </button>
          <button
            class="project-chat-delete"
            type="button"
            data-delete-session="${escapeHtml(session.id)}"
            title="${escapeHtml(uiText("Delete conversation"))}"
            aria-label="${escapeHtml(uiText(`Delete ${session.title || "conversation"}`))}"
          >×</button>
        </article>
      `).join("")
    : `
      <div class="project-detail-empty compact">
        <strong>${escapeHtml(uiText("No conversations yet"))}</strong>
        <p>${escapeHtml(uiText("Start a chat and the model will use this project's sources as its reference base."))}</p>
      </div>
    `;
}

async function openProjectDetail(projectId) {
  const exists = state.projects.some((project) => project.id === projectId);
  if (!exists) return;
  state.currentProject = projectId;
  state.currentSession = null;
  state.chatMessages = [];
  state.uploadedFiles = [];
  state.tokenUsage = emptyTokenUsage();
  renderProjects();
  await loadProjectSources();
  renderProjectDetail();
  persistUiState();
  switchView("projectDetailView");
}

async function selectProject(projectId, { startChat = false } = {}) {
  state.currentProject = projectId || null;
  state.currentSession = null;
  state.chatMessages = [];
  state.uploadedFiles = [];
  state.tokenUsage = emptyTokenUsage();
  renderProjects();
  renderAttachments();
  setEmptyChat();
  persistUiState();
  await loadProjectSources();
  if (startChat) {
    switchView("chatView");
    await startChatSession({ forceNew: true });
  }
}

async function createProject(event) {
  event.preventDefault();
  const name = els.projectNameInput?.value.trim();
  if (!name) return;
  const kind = els.projectKindInput?.value || "knowledge";
  const body = { name, kind, owner_id: state.currentResearcher || null };
  if (kind === "paper_review") {
    body.paper_title = els.paperTitleInput?.value.trim() || "";
    body.field = els.paperFieldInput?.value.trim() || "";
    body.target_venue = els.paperVenueInput?.value.trim() || "";
    body.article_type = els.paperTypeInput?.value || "";
    body.reviewer_profile_id = state.currentResearcher || null;
  }
  const result = await api("/api/projects", {
    method: "POST",
    body: JSON.stringify(body),
  });
  if (!result.ok) {
    addMessage("assistant", result.error || "Could not create the project.", "error");
    return;
  }
  els.projectNameInput.value = "";
  if (els.paperTitleInput) els.paperTitleInput.value = "";
  if (els.paperFieldInput) els.paperFieldInput.value = "";
  if (els.paperVenueInput) els.paperVenueInput.value = "";
  if (els.projectKindInput) els.projectKindInput.value = "knowledge";
  if (els.paperMetaFields) els.paperMetaFields.hidden = true;
  els.projectCreateForm.hidden = true;
  await refreshProjects();
  await openProjectDetail(result.project.id);
}

async function refreshProjects() {
  const owner = state.currentResearcher
    ? `?owner=${encodeURIComponent(state.currentResearcher)}`
    : "";
  const result = await api(`/api/projects${owner}`);
  state.projects = result.projects || [];
  if (state.currentProject && !state.projects.some((item) => item.id === state.currentProject)) {
    state.currentProject = null;
    state.projectSources = [];
  }
  renderProjects();
  if (state.currentProject) await loadProjectSources();
  if (state.activeView === "projectDetailView") renderProjectDetail();
}

function currentResearcherInfo() {
  return state.researchers.find((item) => item.id === state.currentResearcher) || null;
}

function renderResearchers() {
  if (!els.researcherSelect) return;
  els.researcherSelect.innerHTML = [
    `<option value="">${escapeHtml(uiText("No researcher"))}</option>`,
    ...state.researchers.map((researcher) => (
      `<option value="${escapeHtml(researcher.id)}">${escapeHtml(researcher.name)}</option>`
    )),
    `<option value="__new__">${escapeHtml(uiText("+ New researcher…"))}</option>`,
  ].join("");
  els.researcherSelect.value = currentResearcherInfo() ? state.currentResearcher : "";
}

async function refreshResearchers() {
  const result = await api("/api/researchers");
  state.researchers = result.researchers || [];
  if (state.currentResearcher && !currentResearcherInfo()) {
    state.currentResearcher = null;
  }
  renderResearchers();
}

const LENS_PREF_KEYS = [
  ["scope", "Journal fit"],
  ["novelty", "Contribution & novelty"],
  ["methodology", "Methodology"],
  ["field_expert", "Field-specific"],
  ["adversarial", "Reviewer 2"],
  ["format", "Formatting"],
];

function renderLensPrefGrid(prefs) {
  if (!els.researcherLensGrid) return;
  prefs = prefs || {};
  els.researcherLensGrid.innerHTML = LENS_PREF_KEYS.map(([key, label]) => {
    const value = prefs[key] || "";
    const options = ["", "low", "medium", "high"].map((level) => {
      const text = level || uiText("default");
      const selected = level === value ? " selected" : "";
      return `<option value="${level}"${selected}>${escapeHtml(text)}</option>`;
    }).join("");
    return `<label class="researcher-lens-item">${escapeHtml(uiText(label))}` +
      `<select data-lens="${key}">${options}</select></label>`;
  }).join("");
}

function openResearcherProfile({ create = false } = {}) {
  const profile = create ? null : currentResearcherInfo();
  state.researcherFormMode = profile ? "edit" : "new";
  if (els.researcherFormTitle) {
    els.researcherFormTitle.textContent = uiText(profile ? "Edit profile" : "New researcher");
  }
  if (els.researcherName) els.researcherName.value = profile?.name || "";
  if (els.researcherEmail) els.researcherEmail.value = profile?.email || "";
  if (els.researcherFields) els.researcherFields.value = (profile?.fields || []).join(", ");
  if (els.researcherVenues) els.researcherVenues.value = (profile?.default_venues || []).join(", ");
  if (els.researcherStyle) els.researcherStyle.value = profile?.reviewing_style || "";
  if (els.researcherGuidelines) els.researcherGuidelines.value = (profile?.preferred_guidelines || []).join(", ");
  renderLensPrefGrid(profile?.lens_preferences);
  if (els.deleteResearcher) els.deleteResearcher.hidden = !profile;
  renderResearchers();
  switchView("researcherView");
}

function _collectResearcherForm() {
  const lens_preferences = {};
  els.researcherLensGrid?.querySelectorAll("select[data-lens]").forEach((select) => {
    if (select.value) lens_preferences[select.dataset.lens] = select.value;
  });
  return {
    name: els.researcherName?.value.trim() || "",
    email: els.researcherEmail?.value.trim() || "",
    fields: els.researcherFields?.value.trim() || "",
    default_venues: els.researcherVenues?.value.trim() || "",
    reviewing_style: els.researcherStyle?.value.trim() || "",
    preferred_guidelines: els.researcherGuidelines?.value.trim() || "",
    lens_preferences,
  };
}

async function saveResearcherProfile(event) {
  event.preventDefault();
  const body = _collectResearcherForm();
  if (!body.name) {
    addMessage("assistant", uiText("A researcher name is required."), "error");
    return;
  }
  const editing = state.researcherFormMode === "edit" && state.currentResearcher;
  const result = await api(
    editing ? `/api/researchers/${encodeURIComponent(state.currentResearcher)}` : "/api/researchers",
    { method: editing ? "PATCH" : "POST", body: JSON.stringify(body) },
  );
  if (!result.ok) {
    addMessage("assistant", result.error || "Could not save the researcher.", "error");
    return;
  }
  await refreshResearchers();
  await selectResearcher(result.researcher.id);
  switchView("homeView");
}

async function deleteResearcherProfile() {
  if (state.researcherFormMode !== "edit" || !state.currentResearcher) {
    switchView("homeView");
    return;
  }
  const result = await api(`/api/researchers/${encodeURIComponent(state.currentResearcher)}`, {
    method: "DELETE",
  });
  if (!result.ok) {
    addMessage("assistant", result.error || "Could not delete the researcher.", "error");
    return;
  }
  state.currentResearcher = null;
  await refreshResearchers();
  await refreshProjects();
  switchView("homeView");
}

async function selectResearcher(researcherId) {
  state.currentResearcher = researcherId || null;
  // Switching researcher re-scopes which projects are visible.
  state.currentProject = null;
  state.projectSources = [];
  renderResearchers();
  persistUiState();
  await refreshProjects();
}

async function uploadProjectSources(event) {
  const files = Array.from(event.target.files || []);
  if (!files.length || !state.currentProject) return;
  const input = event.target;
  input.disabled = true;
  for (const file of files) {
    try {
      const content = await readFileAsDataUrl(file);
      const result = await api(`/api/projects/${encodeURIComponent(state.currentProject)}/sources`, {
        method: "POST",
        body: JSON.stringify({ name: file.name, content_base64: content }),
      });
      if (!result.ok) {
        addMessage("assistant", result.error || `Could not add ${file.name}`, "error");
      }
    } catch (error) {
      addMessage("assistant", error.message || `Could not add ${file.name}`, "error");
    }
  }
  input.value = "";
  input.disabled = false;
  await refreshProjects();
  renderProjectDetail();
}

function renderSystem(payload) {
  state.lastSystemPayload = payload;
  if (!payload || !payload.ok || !payload.hardware) {
    els.systemSummary.textContent = uiText(payload?.error || "Could not read the hardware.");
    els.recommendationsStrip.innerHTML = "";
    return;
  }

  const hardware = payload.hardware;
  const disk = payload.disk || {};
  const ramFreePercent = hardware.ram_total_gb
    ? hardware.ram_available_gb / hardware.ram_total_gb * 100
    : 0;
  const budgetBase = hardware.inference_budget_theoretical_gb || hardware.inference_budget_gb || 0;
  const budgetPercent = budgetBase
    ? hardware.inference_budget_available_gb / budgetBase * 100
    : 0;

  els.systemSummary.textContent = uiText(hardware.memory_pressure
    ? "Memory is under pressure: closing apps may allow larger models."
    : "Your machine is ready for compatible local models.");

  els.ramValue.textContent = uiText(`${formatGb(hardware.ram_available_gb)} free`);
  els.ramMeta.textContent = uiText(`${formatGb(hardware.ram_total_gb)} total`);
  setMeter(els.ramBar, ramFreePercent);

  els.diskValue.textContent = uiText(`${formatGb(disk.free_gb)} free`);
  els.diskMeta.textContent = uiText(`${formatGb(disk.total_gb)} total in ${disk.path || "workspace"}`);
  setMeter(els.diskBar, disk.free_percent || 0);

  els.budgetValue.textContent = formatGb(hardware.inference_budget_available_gb || hardware.inference_budget_gb);
  els.budgetMeta.textContent = uiText(`Safe now · ceiling ${formatGb(budgetBase)}`);
  setMeter(els.budgetBar, budgetPercent);

  els.modeValue.textContent = hardware.inference_mode === "gpu" ? "GPU" : "CPU";
  els.modeMeta.textContent = uiText(`${hardware.gpu_name || "CPU only"} · ${hardware.cpu_cores} cores · ${hardware.hardware_tier}`);

  const recommendations = payload.recommendations || [];
  if (!recommendations.length) {
    els.recommendationsStrip.innerHTML = `<p class="meta">${escapeHtml(uiText("No recommendations available right now."))}</p>`;
    return;
  }
  els.recommendationsStrip.innerHTML = recommendations.map((item) => `
    <article class="recommendation-card">
      <div>
        <h4>${escapeHtml(item.display_name)}</h4>
        <p>${escapeHtml(item.fit_label)} · ${escapeHtml(item.ollama_tag)}</p>
      </div>
      <div class="mini-meter">
        <span>${escapeHtml(formatGb(item.memory_required_gb))}</span>
        <div class="meter"><i style="width: ${clampPercent(item.memory_usage_percent)}%"></i></div>
      </div>
    </article>
  `).join("");
}

function groupBy(items, key) {
  return items.reduce((groups, item) => {
    const value = item[key] || "Other";
    if (!groups[value]) groups[value] = [];
    groups[value].push(item);
    return groups;
  }, {});
}

function renderTools(payload) {
  state.toolCatalog = payload;
  state.lastToolsPayload = payload;
  if (!els.toolsSummary || !els.quickActions || !els.toolsList) return;
  if (!payload || !payload.ok) {
    els.toolsSummary.textContent = uiText(payload?.error || "Could not load the tools.");
    els.quickActions.innerHTML = "";
    els.toolsList.innerHTML = "";
    return;
  }

  const tools = payload.tools || [];
  const skills = payload.skills || [];
  const mcpServers = payload.mcp_servers || [];
  els.toolsSummary.textContent = uiText(`${tools.length} tools · ${skills.length} skills · ${mcpServers.length} MCP`);

  const actions = payload.actions || [];
  els.quickActions.innerHTML = actions.map((action) => `
    <button
      type="button"
      class="action-chip"
      data-action-prompt="${escapeHtml(action.prompt)}"
      title="${escapeHtml(action.tool)}"
    >
      <span>${escapeHtml(uiText(action.group))}</span>
      ${escapeHtml(action.label)}
    </button>
  `).join("");

  const grouped = groupBy(tools, "group");
  const groupNames = ["Explore", "Edit", "Git", "Planning", "Web", "Notebook", "Skills", "MCP", "System", "Other"]
    .filter((name) => grouped[name]?.length);
  const toolGroups = groupNames.map((group) => `
    <details class="tool-section">
      <summary>
        <span>${escapeHtml(uiText(group))}</span>
        <small>${escapeHtml(uiText(`${grouped[group].length} tools`))}</small>
      </summary>
      <div class="tool-grid">
        ${grouped[group].map((tool) => `
          <article class="tool-card">
            <div>
              <strong>${escapeHtml(tool.name)}</strong>
              <p>${escapeHtml(tool.description)}</p>
            </div>
            <small>${escapeHtml(tool.web_status || "")}</small>
          </article>
        `).join("")}
      </div>
    </details>
  `).join("");

  const skillsHtml = skills.length ? `
    <details class="tool-section">
      <summary>
        <span>${escapeHtml(uiText("Loaded skills"))}</span>
        <small>${escapeHtml(uiText(`${skills.length} available`))}</small>
      </summary>
      <div class="tool-grid">
        ${skills.map((skill) => `
          <article class="tool-card compact">
            <strong>${escapeHtml(skill.name)}</strong>
            <p>${escapeHtml(skill.description)} · ${escapeHtml(skill.source)}</p>
          </article>
        `).join("")}
      </div>
    </details>
  ` : "";

  const mcpHtml = mcpServers.length ? `
    <details class="tool-section">
      <summary>
        <span>${escapeHtml(uiText("Configured MCP servers"))}</span>
        <small>${escapeHtml(uiText(`${mcpServers.length} integrations`))}</small>
      </summary>
      <div class="tool-grid">
        ${mcpServers.map((server) => `
          <article class="tool-card compact">
            <strong>${escapeHtml(server.name)}</strong>
            <p>${escapeHtml(server.command)}</p>
          </article>
        `).join("")}
      </div>
    </details>
  ` : "";

  els.toolsList.innerHTML = toolGroups + skillsHtml + mcpHtml;
}

function applyActionPrompt(prompt) {
  const current = els.messageInput.value.trim();
  els.messageInput.value = current ? `${current}\n\n${prompt}` : prompt;
  if (els.promptActionsMenu) {
    els.promptActionsMenu.open = false;
  }
  switchView("chatView");
  window.setTimeout(() => {
    els.messageInput.focus();
    els.messageInput.selectionStart = els.messageInput.value.length;
    els.messageInput.selectionEnd = els.messageInput.value.length;
  }, 60);
}

function renderOllamaLocation(health) {
  const api = health.ollama_base_url || "Ollama API not configured";
  const executable = health.ollama_executable || "Executable not found in PATH";
  const modelsDir = health.ollama_models_dir || "Models folder not detected";
  return `
    <span><b>${escapeHtml(uiText("API"))}</b>${escapeHtml(uiText(api))}</span>
    <span><b>${escapeHtml(uiText("App"))}</b>${escapeHtml(uiText(executable))}</span>
    <span><b>${escapeHtml(uiText("Models"))}</b>${escapeHtml(uiText(modelsDir))}</span>
  `;
}

async function refreshAll() {
  const health = await api("/api/health");
  els.ollamaStatus.textContent = uiText(health.ok ? `Ollama ready (${health.installed_count})` : "Ollama unavailable");
  els.workspaceLabel.innerHTML = renderOllamaLocation(health);

  const systemPayload = await api("/api/system");
  renderSystem(systemPayload);

  const modelsPayload = await api("/api/models");
  state.models = modelsPayload.catalog || [];
  state.installed = modelsPayload.installed || [];
  renderModelSelect();
  renderModels();
  renderTokenInfo();

  await refreshResearchers();
  await refreshProjects();

  const sessions = await api("/api/sessions");
  state.allSessions = sessions.sessions || [];
  renderSessions(state.allSessions);
  if (state.currentProject) renderProjectDetail();

  const toolsPayload = await api("/api/tools");
  renderTools(toolsPayload);
}

async function runRefreshFromButton(button) {
  if (!button) return;
  const label = button.dataset.defaultLabel || button.textContent.trim() || "Refresh data";
  button.dataset.defaultLabel = label;
  button.disabled = true;
  button.innerHTML = `<span class="tiny-loader button-loader" aria-hidden="true"></span><span>${escapeHtml(uiText("Refreshing"))}</span>`;
  try {
    await refreshAll();
  } finally {
    button.disabled = false;
    button.textContent = uiText(label);
  }
}

async function sendMessage(event) {
  event.preventDefault();
  if (activeChatRequest) {
    stopActiveChatRequest();
    return;
  }
  const message = els.messageInput.value.trim();
  const files = [...state.uploadedFiles];
  if (!message && !files.length) return;
  const model = els.modelSelect.value;
  const prompt = message || "Read and summarize the attached files.";
  const sessionId = state.currentSession;
  addMessage("user", buildDisplayMessage(message, files));
  els.messageInput.value = "";
  state.uploadedFiles = [];
  renderAttachments();
  const controller = new AbortController();
  const requestId = createRequestId();
  activeChatRequest = { controller, requestId };
  setChatRequestRunning(true);
  persistUiState();
  const thinkingNode = addThinkingMessage(prompt, files);
  const requestStartedAt = Date.now();

  try {
    const result = await api("/api/chat", {
      method: "POST",
      signal: controller.signal,
      body: JSON.stringify({
        message: prompt,
        attachments: files,
        model,
        session_id: sessionId,
        request_id: requestId,
        multi_agent: Boolean(els.agentsMode?.checked),
        project_id: state.currentProject,
        researcher_id: state.currentResearcher,
        stream: false,
      }),
    });

    state.currentSession = result.session_id || state.currentSession;
    removeThinkingMessage(thinkingNode);

    if (result.cancelled) {
      addMessage(
        "assistant",
        "Stopped. You can edit the request or start a new task.",
        "stopped",
        {
          duration_ms: Date.now() - requestStartedAt,
          process_log: result.process_log,
        },
      );
    } else if (result.ok) {
      applyTokenUsage(result.usage);
      addMessage(
        "assistant",
        result.answer || "(no response)",
        "",
        {
          duration_ms: Date.now() - requestStartedAt,
          process_log: result.process_log,
        },
      );
    } else {
      addMessage(
        "assistant",
        result.error || "Unknown error",
        "error",
        {
          duration_ms: Date.now() - requestStartedAt,
          process_log: result.process_log,
        },
      );
    }
    refreshAll();
  } catch (error) {
    removeThinkingMessage(thinkingNode);
    if (error.name === "AbortError") {
      addMessage(
        "assistant",
        "Stopped. You can edit the request or start a new task.",
        "stopped",
        {
          duration_ms: Date.now() - requestStartedAt,
          process_log: thinkingNode?._processEntries,
        },
      );
      return;
    }
    addMessage(
      "assistant",
      error.message || "Could not reach Ci2Lab.",
      "error",
      { duration_ms: Date.now() - requestStartedAt },
    );
  } finally {
    activeChatRequest = null;
    setChatRequestRunning(false);
    persistUiState();
  }
}

async function loadSessionIntoChat(sessionId) {
  const result = await api(`/api/sessions/${encodeURIComponent(sessionId)}`);
  if (!result.ok) {
    addMessage("assistant", result.error || "Could not open the session", "error");
    return;
  }

  const session = result.session;
  state.currentProject = session.project_id || null;
  renderProjects();
  await loadProjectSources();
  state.currentSession = session.id;
  state.chatMessages = [];
  state.uploadedFiles = [];
  applyTokenUsage(session.token_usage);
  renderAttachments();
  els.messages.innerHTML = "";
  const sessionModel = state.models.find((model) => (
    model.id === session.model || model.ollama_tag === session.model
  ));
  if (sessionModel && [...els.modelSelect.options].some((option) => option.value === sessionModel.id)) {
    els.modelSelect.value = sessionModel.id;
    updateCommandPreview();
  }

  const visibleMessages = (session.messages || []).filter((message) => (
    message.role === "user" || message.role === "assistant"
  ));
  if (!visibleMessages.length) {
    setEmptyChat();
    addMessage("assistant", `Session ${session.id} resumed.`);
    switchView("chatView");
    return;
  }
  visibleMessages.forEach((message) => {
    addMessage(message.role === "user" ? "user" : "assistant", message.content);
  });
  switchView("chatView");
}

async function deleteSavedSession(sessionId, button) {
  const confirmed = window.confirm("Delete this saved conversation? Its local file will be removed.");
  if (!confirmed) return;

  button.disabled = true;
  button.textContent = uiText("Deleting...");
  const result = await api(`/api/sessions/${encodeURIComponent(sessionId)}`, {
    method: "DELETE",
  });

  if (!result.ok) {
    button.disabled = false;
    button.textContent = uiText("Delete");
    addMessage("assistant", result.error || "Could not delete the session.", "error");
    return;
  }

  if (state.currentSession === sessionId) {
    state.currentSession = null;
    state.chatMessages = [];
    setEmptyChat();
    persistUiState();
  }
  await refreshAll();
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function pollPullTask(taskId, tag) {
  if (state.pullPolls[taskId]) return;
  state.pullPolls[taskId] = true;
  try {
    while (true) {
      await delay(900);
      const result = await api(`/api/models/pull/${encodeURIComponent(taskId)}`);
      if (!result.ok) {
        state.pullTasks[tag] = {
          id: taskId,
          tag,
          status: "Could not query the download",
          percent: 0,
          completed: 0,
          total: 0,
          done: true,
          ok: false,
          error: result.error || "Unknown error",
        };
        renderModels();
        break;
      }

      state.pullTasks[tag] = result.task;
      renderModels();
      if (result.task.done) {
        if (!result.task.ok) {
          addMessage("assistant", result.task.error || "Could not download the model", "error");
        }
        await refreshAll();
        break;
      }
    }
  } finally {
    delete state.pullPolls[taskId];
  }
}

async function pollDeleteTask(taskId, tag) {
  if (state.deletePolls[taskId]) return;
  state.deletePolls[taskId] = true;
  try {
    while (true) {
      await delay(700);
      const result = await api(`/api/models/delete/${encodeURIComponent(taskId)}`);
      if (!result.ok) {
        state.deleteTasks[tag] = {
          id: taskId,
          tag,
          status: "Could not query the uninstall",
          percent: 0,
          done: true,
          ok: false,
          error: result.error || "Unknown error",
        };
        renderModels();
        break;
      }

      state.deleteTasks[tag] = result.task;
      renderModels();
      if (result.task.done) {
        if (!result.task.ok) {
          addMessage("assistant", result.task.error || "Could not uninstall the model", "error");
        }
        await refreshAll();
        break;
      }
    }
  } finally {
    delete state.deletePolls[taskId];
  }
}

async function handleModelAction(event) {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  const action = button.dataset.action;
  const tag = button.dataset.tag;
  if (action === "use") {
    els.modelSelect.value = button.dataset.model;
    updateCommandPreview();
    switchView("chatView");
    if (!state.currentSession && !state.chatMessages.length) {
      await startChatSession({ forceNew: true });
    }
    return;
  }
  button.disabled = true;
  button.textContent = uiText(action === "pull" ? "Starting..." : "Deleting...");
  const endpoint = action === "pull" ? "/api/models/pull" : "/api/models/delete";
  const result = await api(endpoint, {
    method: "POST",
    body: JSON.stringify({ tag }),
  });
  if (!result.ok) {
    addMessage("assistant", result.error || "Could not complete the action", "error");
    await refreshAll();
    return;
  }

  if (action === "pull") {
    state.pullTasks[tag] = result.task;
    renderModels();
    pollPullTask(result.task_id, tag);
    return;
  }

  state.deleteTasks[tag] = result.task;
  renderModels();
  pollDeleteTask(result.task_id, tag);
}

function handleModelSelectChange() {
  updateCommandPreview();
  renderTokenInfo();
  persistUiState();
}

function toggleControlHelp(button) {
  const target = document.getElementById(button.dataset.helpToggle || "");
  if (!target) return;
  const expanded = button.getAttribute("aria-expanded") === "true";
  button.setAttribute("aria-expanded", String(!expanded));
  target.hidden = expanded;
}

function bindEvents() {
  els.languageButtons?.forEach((button) => {
    button.addEventListener("click", () => {
      setDisplayLanguage(button.dataset.language || "en");
      els.languageTrigger?.focus();
    });
  });
  els.languageControl?.addEventListener("mouseenter", () => {
    els.languageTrigger?.setAttribute("aria-expanded", "true");
  });
  els.languageControl?.addEventListener("mouseleave", () => {
    els.languageTrigger?.setAttribute("aria-expanded", "false");
  });
  els.languageControl?.addEventListener("focusin", () => {
    els.languageTrigger?.setAttribute("aria-expanded", "true");
  });
  els.languageControl?.addEventListener("focusout", (event) => {
    if (!els.languageControl?.contains(event.relatedTarget)) {
      els.languageTrigger?.setAttribute("aria-expanded", "false");
    }
  });
  els.chatForm.addEventListener("submit", sendMessage);
  els.fileInput.addEventListener("change", uploadSelectedFiles);
  els.attachmentsList.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-remove-attachment]");
    if (!button) return;
    removeAttachment(button.dataset.removeAttachment);
  });
  els.modelSelect.addEventListener("change", handleModelSelectChange);
  els.projectSelect?.addEventListener("change", async () => {
    await selectProject(els.projectSelect.value, { startChat: true });
  });
  els.researcherSelect?.addEventListener("change", async () => {
    const value = els.researcherSelect.value;
    if (value === "__new__") {
      openResearcherProfile({ create: true });
      return;
    }
    await selectResearcher(value);
  });
  els.openResearcherProfile?.addEventListener("click", () => {
    openResearcherProfile({ create: !state.currentResearcher });
  });
  els.researcherForm?.addEventListener("submit", saveResearcherProfile);
  els.deleteResearcher?.addEventListener("click", deleteResearcherProfile);
  els.cancelResearcher?.addEventListener("click", () => switchView("homeView"));
  els.projectKindInput?.addEventListener("change", () => {
    if (els.paperMetaFields) {
      els.paperMetaFields.hidden = els.projectKindInput.value !== "paper_review";
    }
  });
  els.projectCreateForm?.addEventListener("submit", createProject);
  els.showProjectCreate?.addEventListener("click", () => {
    els.projectCreateForm.hidden = false;
    els.projectNameInput.focus();
  });
  els.cancelProjectCreate?.addEventListener("click", () => {
    els.projectCreateForm.hidden = true;
    els.projectNameInput.value = "";
  });
  els.backToProjects?.addEventListener("click", () => switchView("projectsView"));
  els.newProjectChat?.addEventListener("click", async () => {
    await selectProject(state.currentProject, { startChat: true });
  });
  els.projectsList?.addEventListener("click", async (event) => {
    const deleteButton = event.target.closest("button[data-delete-project]");
    if (deleteButton) {
      const project = state.projects.find((item) => item.id === deleteButton.dataset.deleteProject);
      if (!window.confirm(`Delete “${project?.name || "this project"}” and all its local sources?`)) return;
      const result = await api(`/api/projects/${encodeURIComponent(deleteButton.dataset.deleteProject)}`, {
        method: "DELETE",
      });
      if (!result.ok) {
        addMessage("assistant", result.error || "Could not delete the project.", "error");
        return;
      }
      if (state.currentProject === deleteButton.dataset.deleteProject) {
        state.currentProject = null;
        state.currentSession = null;
        state.projectSources = [];
      }
      await refreshProjects();
      persistUiState();
      return;
    }
    const projectCard = event.target.closest("[data-open-project]");
    if (projectCard) await openProjectDetail(projectCard.dataset.openProject);
  });
  els.projectsList?.addEventListener("keydown", async (event) => {
    if (!["Enter", " "].includes(event.key)) return;
    const projectCard = event.target.closest("[data-open-project]");
    if (!projectCard || event.target.closest("button")) return;
    event.preventDefault();
    await openProjectDetail(projectCard.dataset.openProject);
  });
  els.projectSourceInput?.addEventListener("change", uploadProjectSources);
  els.projectDetailSourceInput?.addEventListener("change", uploadProjectSources);
  els.toggleProjectSources?.addEventListener("click", () => {
    const willShow = els.projectSourcesList.hidden;
    els.projectSourcesList.hidden = !willShow;
    els.toggleProjectSources.textContent = uiText(willShow ? "Hide sources" : "View sources");
  });
  els.projectSourcesList?.addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-delete-source]");
    if (!button || !state.currentProject) return;
    const result = await api(
      `/api/projects/${encodeURIComponent(state.currentProject)}/sources/${encodeURIComponent(button.dataset.deleteSource)}`,
      { method: "DELETE" },
    );
    if (!result.ok) {
      addMessage("assistant", result.error || "Could not remove the source.", "error");
      return;
    }
    await refreshProjects();
  });
  els.projectDetailSources?.addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-delete-source]");
    if (!button || !state.currentProject) return;
    const result = await api(
      `/api/projects/${encodeURIComponent(state.currentProject)}/sources/${encodeURIComponent(button.dataset.deleteSource)}`,
      { method: "DELETE" },
    );
    if (!result.ok) {
      addMessage("assistant", result.error || "Could not remove the source.", "error");
      return;
    }
    await refreshProjects();
  });
  els.projectChatsList?.addEventListener("click", (event) => {
    const deleteButton = event.target.closest("button[data-delete-session]");
    if (deleteButton) {
      deleteSavedSession(deleteButton.dataset.deleteSession, deleteButton);
      return;
    }
    const button = event.target.closest("button[data-project-session]");
    if (!button) return;
    loadSessionIntoChat(button.dataset.projectSession);
  });
  els.modelSearch.addEventListener("input", renderModels);
  els.modelsList.addEventListener("click", handleModelAction);
  els.refreshButton.addEventListener("click", () => runRefreshFromButton(els.refreshButton));
  els.agentsModeButton?.addEventListener("click", toggleAgentsMode);
  els.toolsDrawerToggle?.addEventListener("click", toggleToolsDrawer);
  els.toolsDrawerClose?.addEventListener("click", () => setToolsDrawer(false));
  els.toolsBackdrop?.addEventListener("click", () => setToolsDrawer(false));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && els.toolsPanel?.classList.contains("open")) {
      setToolsDrawer(false);
    }
  });
  els.quickActions?.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-action-prompt]");
    if (!button) return;
    applyActionPrompt(button.dataset.actionPrompt || "");
  });
  els.tokenCounter?.addEventListener("click", () => {
    renderTokenInfo();
    switchView("tokenInfoView");
  });
  els.backToChatFromTokens?.addEventListener("click", () => switchView("chatView"));
  document.querySelectorAll("[data-help-toggle]").forEach((button) => {
    button.addEventListener("click", () => toggleControlHelp(button));
  });
  els.newChat.addEventListener("click", async () => {
    state.currentSession = null;
    state.chatMessages = [];
    state.uploadedFiles = [];
    state.tokenUsage = emptyTokenUsage();
    if (els.agentsMode) {
      els.agentsMode.checked = false;
    }
    updateTokenDisplay();
    updateAgentsModeState({ persist: false });
    renderAttachments();
    setEmptyChat();
    persistUiState();
    switchView("chatView");
    await startChatSession({ forceNew: true });
  });
  els.sessionsList.addEventListener("click", (event) => {
    const deleteButton = event.target.closest("button[data-delete-session]");
    if (deleteButton) {
      deleteSavedSession(deleteButton.dataset.deleteSession, deleteButton);
      return;
    }
    const button = event.target.closest("button[data-session]");
    if (!button) return;
    loadSessionIntoChat(button.dataset.session);
  });
  els.navButtons.forEach((button) => {
    if (button.id === "newChat") return;
    button.addEventListener("click", async () => {
      if (button.id === "openChat") {
        await selectProject("", { startChat: true });
        return;
      }
      switchView(button.dataset.view || "homeView", button.dataset.scroll || null);
    });
  });
}

restoreUiState();
syncLanguageControl();
translateNode(document.body);
const translationObserver = new MutationObserver((mutations) => {
  mutations.forEach((mutation) => {
    mutation.addedNodes.forEach(translateNode);
    if (mutation.type === "characterData") translateNode(mutation.target);
    if (mutation.type === "attributes") translateNode(mutation.target);
  });
});
translationObserver.observe(document.body, {
  childList: true,
  subtree: true,
  characterData: true,
  attributes: true,
  attributeFilter: ["placeholder", "title", "aria-label"],
});
state.tokenUsage = normalizeTokenUsage(state.tokenUsage);
if (els.agentsMode) {
  els.agentsMode.checked = Boolean(state.agentsMode);
}
updateTokenDisplay();
updateAgentsModeState({ persist: false });
renderChatMessages();
renderAttachments();
bindEvents();
renderTokenInfo();
switchView(state.activeView || "homeView");
refreshAll().catch((error) => {
  els.ollamaStatus.textContent = "UI error";
  addMessage("assistant", error.message, "error");
});
